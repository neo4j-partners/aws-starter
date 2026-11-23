import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { Stack, type StackProps } from 'aws-cdk-lib';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
}

/** Must match the Runtime name in agentcore/agentcore.json. */
export const RUNTIME_NAME = 'fraud_memory_agent';

/**
 * Connection settings copied from the deploy shell into the Runtime environment.
 * GATEWAY_URL and GATEWAY_SCOPES come from demos/fraud-amazon-quick/.mcp-credentials.json.
 */
const REQUIRED_VARS = ['GATEWAY_URL', 'GATEWAY_SCOPES'] as const;

/** NAMS settings from demos/fraud-amazon-quick/.env, copied only when set. */
const OPTIONAL_VARS = ['MEMORY_ENDPOINT', 'MEMORY_WORKSPACE_ID', 'MEMORY_TOOLS'] as const;

/** Settings that must use a scheme with TLS. */
const REQUIRED_SCHEMES: Record<string, readonly string[]> = {
  GATEWAY_URL: ['https://'],
  MEMORY_ENDPOINT: ['https://'],
};

/** The provider path each credential type lives under in the token vault. */
const PROVIDER_PATHS = {
  ApiKeyCredentialProvider: 'apikeycredentialprovider',
  OAuthCredentialProvider: 'oauth2credentialprovider',
} as const;

/** The Identity action that returns each credential type to a workload. */
const PROVIDER_ACTIONS = {
  ApiKeyCredentialProvider: 'bedrock-agentcore:GetResourceApiKey',
  OAuthCredentialProvider: 'bedrock-agentcore:GetResourceOauth2Token',
} as const;

/** A complete secret ARN ends in the six-character suffix Secrets Manager adds. */
const COMPLETE_SECRET_ARN = /^arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:\d{12}:secret:[^*?]+-[A-Za-z0-9]{6}$/;

/** A credential provider ARN, split into the token vault prefix, the type path and the name. */
const PROVIDER_ARN =
  /^(arn:aws[a-z-]*:bedrock-agentcore:[a-z0-9-]+:\d{12}:)token-vault\/default\/([a-z0-9]+)\/([A-Za-z0-9_-]+)$/;

/** The environment variable the construct would set for a credential; agent code reads it. */
export function credentialNameVar(credentialName: string): string {
  return `CREDENTIAL_${credentialName.toUpperCase().replace(/[.-]/g, '_')}_NAME`;
}

/**
 * Read the connection settings from the deploy environment. `agent.sh deploy` loads them from
 * demos/fraud-amazon-quick/.env and .mcp-credentials.json, which sit outside the code zip.
 * Throws one error naming every missing or malformed variable, so synth stops before
 * anything is deployed.
 */
function readDeployEnv(): Record<string, string> {
  const values: Record<string, string> = {};
  const problems: string[] = [];
  for (const name of REQUIRED_VARS) {
    const value = process.env[name]?.trim();
    if (!value) {
      problems.push(`${name} is not set`);
    } else {
      values[name] = value;
    }
  }
  for (const name of OPTIONAL_VARS) {
    const value = process.env[name]?.trim();
    if (value) {
      values[name] = value;
    }
  }
  for (const [name, schemes] of Object.entries(REQUIRED_SCHEMES)) {
    if (values[name] && !schemes.some((scheme) => values[name].startsWith(scheme))) {
      problems.push(`${name} must start with ${schemes.join(' or ')}`);
    }
  }
  if (problems.length > 0) {
    throw new Error(
      `Missing deploy settings for runtime "${RUNTIME_NAME}":\n  - ${problems.join('\n  - ')}\n` +
        'Set them in demos/fraud-amazon-quick/.env and .mcp-credentials.json, and deploy with ./agent.sh deploy.',
    );
  }
  return values;
}

/** One declared credential with the exact ARNs the CLI recorded when it provisioned it. */
interface ResolvedCredential {
  readonly name: string;
  readonly action: string;
  readonly providerArn: string;
  readonly providerName: string;
  readonly tokenVaultPrefix: string;
  readonly secretArn: string;
}

/**
 * Match each credential the spec declares to the ARNs in deployed-state.json. The CLI provisions
 * the providers and records them before it synthesizes, so a missing or malformed entry means
 * the deploy did not go through `agentcore deploy`. Throws one error naming every problem.
 */
function resolveCredentials(application: AgentCoreApplicationProps): ResolvedCredential[] {
  const resolved: ResolvedCredential[] = [];
  const problems: string[] = [];
  for (const credential of application.spec.credentials ?? []) {
    const { name, authorizerType } = credential;
    if (authorizerType !== 'ApiKeyCredentialProvider' && authorizerType !== 'OAuthCredentialProvider') {
      problems.push(`credential "${name}" has unsupported type ${authorizerType}`);
      continue;
    }
    const deployed = application.credentials?.[name];
    if (deployed === undefined) {
      problems.push(`credential "${name}" has no provisioned provider in deployed-state.json`);
      continue;
    }
    const match = PROVIDER_ARN.exec(deployed.credentialProviderArn);
    if (match === null || match[2] !== PROVIDER_PATHS[authorizerType]) {
      problems.push(`credential "${name}" has a malformed provider ARN: ${deployed.credentialProviderArn}`);
      continue;
    }
    if (deployed.clientSecretArn === undefined || !COMPLETE_SECRET_ARN.test(deployed.clientSecretArn)) {
      problems.push(`credential "${name}" has no complete secret ARN in deployed-state.json`);
      continue;
    }
    resolved.push({
      name,
      action: PROVIDER_ACTIONS[authorizerType],
      providerArn: deployed.credentialProviderArn,
      providerName: match[3],
      tokenVaultPrefix: match[1],
      secretArn: deployed.clientSecretArn,
    });
  }
  if (problems.length > 0) {
    throw new Error(
      `Credential problems for runtime "${RUNTIME_NAME}":\n  - ${problems.join('\n  - ')}\n` +
        'Deploy with ./agent.sh deploy, which declares and provisions the credentials.',
    );
  }
  return resolved;
}

/**
 * The stack the AgentCore CLI deploys. Everything declared in agentcore/agentcore.json is
 * created by the AgentCoreApplication construct, except the credential grants.
 *
 * The construct's own credential grant covers every provider and every Identity secret in the
 * account. So the construct gets the spec without its credentials, and this stack grants the
 * Runtime exactly the providers and secrets the CLI provisioned. The CLI still provisions and
 * deletes the providers, because it reads the credentials from agentcore.json itself.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    const { application } = props;
    this.application = new AgentCoreApplication(this, 'Application', {
      ...application,
      spec: { ...application.spec, credentials: [] },
    });

    // `agent.sh destroy` removes the Runtime from the spec and deploys. With no Runtime there
    // is nothing to configure, and the settings are not needed.
    const runtime = this.application.runtimes.get(RUNTIME_NAME);
    if (runtime === undefined) {
      return;
    }
    const credentials = resolveCredentials(application);
    for (const [name, value] of Object.entries(readDeployEnv())) {
      runtime.addEnvironmentVariable(name, value);
    }
    for (const credential of credentials) {
      runtime.addEnvironmentVariable(credentialNameVar(credential.name), credential.providerName);
      // The token vault, the provider, and the Runtime's workload identity, matching the
      // resources the Identity service authorizes for a credential read.
      runtime.addToPolicy(
        new PolicyStatement({
          actions: [credential.action],
          resources: [
            `${credential.tokenVaultPrefix}token-vault/default`,
            credential.providerArn,
            `${credential.tokenVaultPrefix}workload-identity-directory/default`,
            `${credential.tokenVaultPrefix}workload-identity-directory/default/workload-identity/*`,
          ],
        }),
      );
      runtime.addToPolicy(
        new PolicyStatement({
          actions: ['secretsmanager:GetSecretValue'],
          resources: [credential.secretArn],
        }),
      );
    }
  }
}
