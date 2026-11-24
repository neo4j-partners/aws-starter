import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { Stack, type StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
}

/** Must match the Runtime name in agentcore/agentcore.json. */
export const RUNTIME_NAME = 'supervisor';

/**
 * Plain connection settings, copied from the deploy shell into the Runtime environment.
 * The NEO4J_* settings name the fleet graph, and the MEM_NEO4J_* settings name the memory
 * database. Both come from demos/aircraft-fleet/.env.
 */
export const PLAIN_VARS = [
  'NEO4J_URI',
  'NEO4J_USERNAME',
  'NEO4J_DATABASE',
  'MEM_NEO4J_URI',
  'MEM_NEO4J_USERNAME',
  'MEM_NEO4J_DATABASE',
] as const;

/**
 * Secrets Manager ARNs for the fleet graph and memory passwords. The Runtime gets the ARN and
 * reads the secret at startup. The password itself never reaches the stack.
 */
export const SECRET_ARN_VARS = ['NEO4J_PASSWORD_SECRET_ARN', 'MEM_NEO4J_PASSWORD_SECRET_ARN'] as const;

/** Connection URIs the Runtime dials. The cloud path must use TLS. */
const URI_VARS = ['NEO4J_URI', 'MEM_NEO4J_URI'] as const;
/** The whole value must be scheme://host with an optional port, and nothing after it. */
const TLS_NEO4J_URI = /^(neo4j|bolt)\+s:\/\/[A-Za-z0-9.-]+(:\d{1,5})?$/;

/**
 * A complete secret ARN ends in the six-character suffix Secrets Manager adds. This check
 * catches a name-only ARN, but not a partial ARN whose name happens to end in a dash and six
 * characters, such as `aircraft-fleet/neo4j-abc123`. Such an ARN passes synth, and the
 * Runtime then fails at startup when it reads the secret.
 */
const COMPLETE_SECRET_ARN = /^arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:\d{12}:secret:.+-[A-Za-z0-9]{6}$/;

/**
 * Read the named variables from the deploy environment. `agent.sh deploy` loads them from
 * demos/aircraft-fleet/.env, which sits outside the code zip. Throws one error naming every
 * missing or malformed variable, so synth stops before anything is deployed.
 */
function readDeployEnv(): Record<string, string> {
  const values: Record<string, string> = {};
  const problems: string[] = [];
  for (const name of [...PLAIN_VARS, ...SECRET_ARN_VARS]) {
    const value = process.env[name]?.trim();
    if (!value) {
      problems.push(`${name} is not set`);
    } else {
      values[name] = value;
    }
  }
  for (const name of URI_VARS) {
    if (values[name] && !TLS_NEO4J_URI.test(values[name])) {
      problems.push(`${name} must be neo4j+s://host or bolt+s://host, with an optional :port`);
    }
  }
  for (const name of SECRET_ARN_VARS) {
    if (values[name] && !COMPLETE_SECRET_ARN.test(values[name])) {
      problems.push(`${name} is not a complete Secrets Manager secret ARN (it must end in the -XXXXXX suffix)`);
    }
  }
  if (problems.length > 0) {
    throw new Error(
      `Missing or invalid deploy settings for runtime "${RUNTIME_NAME}":\n  - ${problems.join('\n  - ')}\n` +
        'Fix them in demos/aircraft-fleet/.env and deploy with ./agent.sh deploy.',
    );
  }
  return values;
}

/**
 * The stack the AgentCore CLI deploys. Everything declared in agentcore/agentcore.json is
 * created by the AgentCoreApplication construct. This stack adds the fleet graph and memory
 * settings to the supervisor Runtime and lets its role read exactly the two password secrets.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    this.application = new AgentCoreApplication(this, 'Application', props.application);

    // `agent.sh destroy` removes the Runtime from the spec and deploys. With no Runtime there
    // is nothing to configure, and the settings are not needed.
    const runtime = this.application.runtimes.get(RUNTIME_NAME);
    if (runtime === undefined) {
      return;
    }
    const env = readDeployEnv();
    for (const [name, value] of Object.entries(env)) {
      runtime.addEnvironmentVariable(name, value);
    }
    runtime.grant(
      ['secretsmanager:GetSecretValue'],
      SECRET_ARN_VARS.map((name) => env[name]),
    );
  }
}
