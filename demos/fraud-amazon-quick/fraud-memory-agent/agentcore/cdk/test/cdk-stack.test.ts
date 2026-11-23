/**
 * Synth tests for the fraud agent stack's credential grants.
 *
 * Each test synthesizes the stack from agentcore/agentcore.json with the two credentials
 * agent.sh declares at deploy time and the ARNs the CLI would record in deployed-state.json.
 * The code location is a temporary project with no dependencies, so CodeZip packaging is fast
 * and needs no network. Run with `npm test`.
 */
import { strict as assert } from 'node:assert';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, it } from 'node:test';

import { transformAgentCoreJson, type DeployedCredentials } from '@aws/agentcore-cdk';
import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';

import { AgentCoreStack, RUNTIME_NAME } from '../lib/cdk-stack';

const ACCOUNT = '123456789012';
const REGION = 'us-west-2';
const ARN_PREFIX = `arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:`;
const GATEWAY_PROVIDER = `${ARN_PREFIX}token-vault/default/oauth2credentialprovider/FraudMemory_default_fraud-gateway`;
const NAMS_PROVIDER = `${ARN_PREFIX}token-vault/default/apikeycredentialprovider/FraudMemory_default_nams-api-key`;
const GATEWAY_SECRET = `arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:bedrock-agentcore-identity!default/oauth2/FraudMemory_default_fraud-gateway-AbC123`;
const NAMS_SECRET = `arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:bedrock-agentcore-identity!default/apikey/FraudMemory_default_nams-api-key-XyZ789`;

/** The credentials agent.sh adds to the spec for a deploy. */
const DECLARED = [
  { authorizerType: 'OAuthCredentialProvider', name: 'fraud-gateway', vendor: 'CustomOauth2' },
  { authorizerType: 'ApiKeyCredentialProvider', name: 'nams-api-key' },
];

const DEPLOYED: DeployedCredentials = {
  'fraud-gateway': { credentialProviderArn: GATEWAY_PROVIDER, clientSecretArn: GATEWAY_SECRET },
  'nams-api-key': { credentialProviderArn: NAMS_PROVIDER, clientSecretArn: NAMS_SECRET },
};

const DEPLOY_ENV: Record<string, string> = {
  GATEWAY_URL: 'https://gateway.example.com/mcp',
  GATEWAY_SCOPES: 'neo4j-mcp/invoke',
};

/** Wildcards the construct's own credential grant uses. None may reach the role. */
const BANNED_WILDCARDS = [/apikeycredentialprovider\/\*/, /oauth2credentialprovider\/\*/, /bedrock-agentcore-identity!\*/];

const SPEC_FILE = join(__dirname, '..', '..', '..', 'agentcore.json');
let projectRoot: string;

before(() => {
  projectRoot = mkdtempSync(join(tmpdir(), 'fraud-cdk-test-'));
  mkdirSync(join(projectRoot, 'agentcore'));
  writeFileSync(join(projectRoot, 'pyproject.toml'), '[project]\nname = "synth-test"\nversion = "0.0.0"\ndependencies = []\n');
  writeFileSync(join(projectRoot, 'main.py'), '');
});

after(() => {
  rmSync(projectRoot, { recursive: true, force: true });
});

interface SynthOptions {
  readonly credentials?: readonly object[];
  readonly deployed?: DeployedCredentials;
  readonly runtimes?: boolean;
}

function synth({ credentials = DECLARED, deployed = DEPLOYED, runtimes = true }: SynthOptions = {}): Template {
  const spec = JSON.parse(readFileSync(SPEC_FILE, 'utf-8'));
  spec.credentials = credentials;
  if (!runtimes) {
    spec.runtimes = [];
  }
  const saved = { ...process.env };
  Object.assign(process.env, DEPLOY_ENV);
  try {
    const app = new App();
    const stack = new AgentCoreStack(app, 'AgentCore-FraudMemory-default', {
      env: { account: ACCOUNT, region: REGION },
      application: transformAgentCoreJson(spec, {
        projectRoot,
        credentials: deployed,
        target: { name: 'default', account: ACCOUNT, region: REGION },
      }),
    });
    return Template.fromStack(stack);
  } finally {
    for (const name of Object.keys(DEPLOY_ENV)) {
      if (saved[name] === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = saved[name];
      }
    }
  }
}

/** Every resource string in every IAM policy statement in the template. */
function policyResources(template: Template): string[] {
  const resources: string[] = [];
  for (const policy of Object.values(template.findResources('AWS::IAM::Policy'))) {
    for (const statement of policy.Properties.PolicyDocument.Statement) {
      const listed = Array.isArray(statement.Resource) ? statement.Resource : [statement.Resource];
      resources.push(...listed.map((resource: unknown) => JSON.stringify(resource)));
    }
  }
  return resources;
}

/** The statements that grant `action`, as [actions, resources] pairs. */
function statementsFor(template: Template, action: string): unknown[][] {
  const found: unknown[][] = [];
  for (const policy of Object.values(template.findResources('AWS::IAM::Policy'))) {
    for (const statement of policy.Properties.PolicyDocument.Statement) {
      const actions = Array.isArray(statement.Action) ? statement.Action : [statement.Action];
      if (actions.includes(action)) {
        found.push(Array.isArray(statement.Resource) ? statement.Resource : [statement.Resource]);
      }
    }
  }
  return found;
}

/** The Runtime's environment variables. */
function runtimeEnv(template: Template): Record<string, string> {
  const runtimes = Object.values(template.findResources('AWS::BedrockAgentCore::Runtime'));
  assert.equal(runtimes.length, 1);
  return runtimes[0].Properties.EnvironmentVariables;
}

describe('fraud agent stack', () => {
  it('grants no wildcard on credential providers or Identity secrets', () => {
    const resources = policyResources(synth());
    for (const banned of BANNED_WILDCARDS) {
      const hits = resources.filter((resource) => banned.test(resource));
      assert.deepEqual(hits, [], `role has a ${banned} grant`);
    }
  });

  it('grants the OAuth token read on exactly the Gateway provider', () => {
    const statements = statementsFor(synth(), 'bedrock-agentcore:GetResourceOauth2Token');
    assert.equal(statements.length, 1);
    assert.deepEqual(statements[0], [
      `${ARN_PREFIX}token-vault/default`,
      GATEWAY_PROVIDER,
      `${ARN_PREFIX}workload-identity-directory/default`,
      `${ARN_PREFIX}workload-identity-directory/default/workload-identity/*`,
    ]);
  });

  it('grants the API key read on exactly the NAMS provider', () => {
    const statements = statementsFor(synth(), 'bedrock-agentcore:GetResourceApiKey');
    assert.equal(statements.length, 1);
    assert.deepEqual(statements[0], [
      `${ARN_PREFIX}token-vault/default`,
      NAMS_PROVIDER,
      `${ARN_PREFIX}workload-identity-directory/default`,
      `${ARN_PREFIX}workload-identity-directory/default/workload-identity/*`,
    ]);
  });

  it('grants GetSecretValue on exactly the two provider secrets', () => {
    const statements = statementsFor(synth(), 'secretsmanager:GetSecretValue');
    assert.deepEqual(statements.flat().sort(), [GATEWAY_SECRET, NAMS_SECRET].sort());
  });

  it('sets the provider name and connection variables on the Runtime', () => {
    const env = runtimeEnv(synth());
    assert.equal(env.CREDENTIAL_FRAUD_GATEWAY_NAME, 'FraudMemory_default_fraud-gateway');
    assert.equal(env.CREDENTIAL_NAMS_API_KEY_NAME, 'FraudMemory_default_nams-api-key');
    assert.equal(env.GATEWAY_URL, DEPLOY_ENV.GATEWAY_URL);
    assert.equal(env.GATEWAY_SCOPES, DEPLOY_ENV.GATEWAY_SCOPES);
    assert.equal(env.MEMORY_API_KEY, undefined);
  });

  it('fails synth when a declared credential is not provisioned', () => {
    assert.throws(
      () => synth({ deployed: { 'fraud-gateway': DEPLOYED['fraud-gateway'] } }),
      /credential "nams-api-key" has no provisioned provider/,
    );
  });

  it('fails synth when a provider ARN has the wrong type', () => {
    assert.throws(
      () => synth({ deployed: { ...DEPLOYED, 'nams-api-key': { ...DEPLOYED['nams-api-key'], credentialProviderArn: GATEWAY_PROVIDER } } }),
      /credential "nams-api-key" has a malformed provider ARN/,
    );
  });

  it('fails synth when a secret ARN is a wildcard', () => {
    assert.throws(
      () => synth({ deployed: { ...DEPLOYED, 'nams-api-key': { ...DEPLOYED['nams-api-key'], clientSecretArn: `arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:bedrock-agentcore-identity!*` } } }),
      /credential "nams-api-key" has no complete secret ARN/,
    );
  });

  it('synthesizes with no Runtime and no credentials, as destroy does', () => {
    const template = synth({ credentials: [], deployed: {}, runtimes: false });
    assert.deepEqual(Object.keys(template.findResources('AWS::BedrockAgentCore::Runtime')), []);
  });

  it('names the Runtime the spec declares', () => {
    const spec = JSON.parse(readFileSync(SPEC_FILE, 'utf-8'));
    assert.deepEqual(
      spec.runtimes.map((runtime: { name: string }) => runtime.name),
      [RUNTIME_NAME],
    );
    assert.deepEqual(spec.credentials, []);
  });
});
