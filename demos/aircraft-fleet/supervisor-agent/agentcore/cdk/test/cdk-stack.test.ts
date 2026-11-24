/**
 * Synth tests for the supervisor stack's deploy settings and secret grants.
 *
 * Each test synthesizes the stack from agentcore/agentcore.json with the settings agent.sh
 * exports from demos/aircraft-fleet/.env at deploy time. The code location is a temporary
 * project with no dependencies, so CodeZip packaging is fast and needs no network. Run with
 * `npm test`.
 */
import { strict as assert } from 'node:assert';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, it } from 'node:test';

import { transformAgentCoreJson } from '@aws/agentcore-cdk';
import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';

import { AgentCoreStack, PLAIN_VARS, RUNTIME_NAME, SECRET_ARN_VARS } from '../lib/cdk-stack';

const ACCOUNT = '123456789012';
const REGION = 'us-east-1';
const FLEET_SECRET = `arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:fleet-neo4j-AbC123`;
const MEMORY_SECRET = `arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:fleet-memory-XyZ789`;

/** The settings agent.sh exports for a deploy. */
const DEPLOY_ENV: Record<string, string> = {
  NEO4J_URI: 'neo4j+s://fleet1234.databases.neo4j.io',
  NEO4J_USERNAME: 'neo4j',
  NEO4J_DATABASE: 'neo4j',
  NEO4J_PASSWORD_SECRET_ARN: FLEET_SECRET,
  MEM_NEO4J_URI: 'neo4j+s://memory12.databases.neo4j.io',
  MEM_NEO4J_USERNAME: 'neo4j',
  MEM_NEO4J_DATABASE: 'neo4j',
  MEM_NEO4J_PASSWORD_SECRET_ARN: MEMORY_SECRET,
};

/** Every name the stack reads. Each synth clears them first, so the shell running the tests has no effect. */
const STACK_VARS: readonly string[] = [...PLAIN_VARS, ...SECRET_ARN_VARS];

const SPEC_FILE = join(__dirname, '..', '..', '..', 'agentcore.json');
let projectRoot: string;

before(() => {
  projectRoot = mkdtempSync(join(tmpdir(), 'fleet-supervisor-cdk-test-'));
  mkdirSync(join(projectRoot, 'agentcore'));
  writeFileSync(join(projectRoot, 'pyproject.toml'), '[project]\nname = "synth-test"\nversion = "0.0.0"\ndependencies = []\n');
  writeFileSync(join(projectRoot, 'main.py'), '');
});

after(() => {
  rmSync(projectRoot, { recursive: true, force: true });
});

interface SynthOptions {
  /** The deploy environment. A name set to undefined is left unset. */
  readonly env?: Record<string, string | undefined>;
  readonly runtimes?: boolean;
}

function synth({ env = DEPLOY_ENV, runtimes = true }: SynthOptions = {}): Template {
  const spec = JSON.parse(readFileSync(SPEC_FILE, 'utf-8'));
  if (!runtimes) {
    spec.runtimes = [];
  }
  const saved = { ...process.env };
  for (const name of STACK_VARS) {
    delete process.env[name];
  }
  for (const [name, value] of Object.entries(env)) {
    if (value !== undefined) {
      process.env[name] = value;
    }
  }
  try {
    const app = new App();
    const stack = new AgentCoreStack(app, 'AgentCore-fleetsupervisor-default', {
      env: { account: ACCOUNT, region: REGION },
      application: transformAgentCoreJson(spec, {
        projectRoot,
        credentials: {},
        target: { name: 'default', account: ACCOUNT, region: REGION },
      }),
    });
    return Template.fromStack(stack);
  } finally {
    for (const name of new Set([...STACK_VARS, ...Object.keys(env)])) {
      if (saved[name] === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = saved[name];
      }
    }
  }
}

/** The resources of every statement that grants `action`, one list per statement. */
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

describe('fleet supervisor stack', () => {
  it('sets the fleet graph and memory settings on the Runtime', () => {
    const env = runtimeEnv(synth());
    for (const [name, value] of Object.entries(DEPLOY_ENV)) {
      assert.equal(env[name], value, name);
    }
    assert.equal(env.MODEL_ID, 'global.anthropic.claude-sonnet-5-5');
  });

  it('sets no Gateway settings and no password on the Runtime', () => {
    const env = runtimeEnv(synth({ env: { ...DEPLOY_ENV, NEO4J_PASSWORD: 'p', MEM_NEO4J_PASSWORD: 'p', GATEWAY_URL: 'https://gateway.example.com/mcp' } }));
    const unexpected = Object.keys(env).filter((name) => /PASSWORD$|^GATEWAY_|^CREDENTIAL_/.test(name));
    assert.deepEqual(unexpected, []);
  });

  it('grants GetSecretValue on exactly the two password secrets', () => {
    const statements = statementsFor(synth(), 'secretsmanager:GetSecretValue');
    assert.deepEqual(statements.flat().sort(), [FLEET_SECRET, MEMORY_SECRET].sort());
  });

  for (const name of SECRET_ARN_VARS) {
    it(`fails synth and names ${name} when it is missing`, () => {
      assert.throws(
        () => synth({ env: { ...DEPLOY_ENV, [name]: undefined } }),
        (error: Error) => {
          assert.match(error.message, /^Missing or invalid deploy settings for runtime "supervisor":/);
          assert.match(error.message, new RegExp(`- ${name} is not set\\n`));
          assert.match(error.message, /Fix them in demos\/aircraft-fleet\/\.env and deploy with \.\/agent\.sh deploy\./);
          return true;
        },
      );
    });

    it(`fails synth when ${name} is blank`, () => {
      assert.throws(() => synth({ env: { ...DEPLOY_ENV, [name]: '  ' } }), new RegExp(`- ${name} is not set`));
    });

    it(`fails synth when ${name} has no secret suffix`, () => {
      const partial = `arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:fleet`;
      assert.throws(
        () => synth({ env: { ...DEPLOY_ENV, [name]: partial } }),
        new RegExp(`- ${name} is not a complete Secrets Manager secret ARN`),
      );
    });
  }

  it('names every missing setting in one error', () => {
    assert.throws(
      () => synth({ env: {} }),
      (error: Error) => {
        for (const name of STACK_VARS) {
          assert.match(error.message, new RegExp(`- ${name} is not set`));
        }
        return true;
      },
    );
  });

  for (const name of ['NEO4J_URI', 'MEM_NEO4J_URI']) {
    for (const uri of ['neo4j://fleet1234.databases.neo4j.io', 'bolt://localhost:7687', 'neo4j+s://host/path']) {
      it(`fails synth when ${name} is ${uri}`, () => {
        assert.throws(
          () => synth({ env: { ...DEPLOY_ENV, [name]: uri } }),
          new RegExp(`- ${name} must be neo4j\\+s://host or bolt\\+s://host, with an optional :port`),
        );
      });
    }
  }

  it('accepts bolt+s with a port', () => {
    const env = runtimeEnv(synth({ env: { ...DEPLOY_ENV, NEO4J_URI: 'bolt+s://fleet.example.com:7687' } }));
    assert.equal(env.NEO4J_URI, 'bolt+s://fleet.example.com:7687');
  });

  it('synthesizes with no Runtime and no settings, as destroy does', () => {
    const template = synth({ env: {}, runtimes: false });
    assert.deepEqual(Object.keys(template.findResources('AWS::BedrockAgentCore::Runtime')), []);
    assert.deepEqual(statementsFor(template, 'secretsmanager:GetSecretValue'), []);
  });

  it('names the Runtime the spec declares, with no credentials', () => {
    const spec = JSON.parse(readFileSync(SPEC_FILE, 'utf-8'));
    assert.deepEqual(
      spec.runtimes.map((runtime: { name: string }) => runtime.name),
      [RUNTIME_NAME],
    );
    assert.deepEqual(spec.credentials, []);
  });
});
