import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { Stack, type StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
}

/** Must match the Runtime name in agentcore/agentcore.json. */
const RUNTIME_NAME = 'graphrag_agent';

/** Plain connection settings, copied from the deploy shell into the Runtime environment. */
const PLAIN_VARS = [
  'NEO4J_URI',
  'NEO4J_USERNAME',
  'NEO4J_DATABASE',
  'MEM_NEO4J_URI',
  'MEM_NEO4J_USERNAME',
  'MEM_NEO4J_DATABASE',
] as const;

/**
 * Secrets Manager ARNs for the two Neo4j passwords. The Runtime gets the ARN and reads the
 * secret at startup. The password itself never reaches the stack.
 */
const SECRET_ARN_VARS = ['NEO4J_PASSWORD_SECRET_ARN', 'MEM_NEO4J_PASSWORD_SECRET_ARN'] as const;

/** Connection URIs the Runtime dials. A Runtime cannot reach localhost, and the cloud path must use TLS. */
const URI_VARS = ['NEO4J_URI', 'MEM_NEO4J_URI'] as const;
const TLS_NEO4J_URI = /^(neo4j|bolt)\+s:\/\/[^/\s]+/;

/** A complete secret ARN ends in the six-character suffix Secrets Manager adds. */
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
      problems.push(`${name} must use the neo4j+s:// or bolt+s:// scheme`);
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
 * created by the AgentCoreApplication construct. This stack adds the Neo4j settings to the
 * graphrag_agent Runtime and lets its role read exactly the two password secrets.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    this.application = new AgentCoreApplication(this, 'Application', props.application);

    const env = readDeployEnv();
    const runtime = this.application.runtime(RUNTIME_NAME);
    for (const [name, value] of Object.entries(env)) {
      runtime.addEnvironmentVariable(name, value);
    }
    runtime.grant(
      ['secretsmanager:GetSecretValue'],
      SECRET_ARN_VARS.map((name) => env[name]),
    );
  }
}
