/**
 * Synth tests for the hosted fleet UI stack.
 *
 * Each test synthesizes the stack against a temporary build context that holds a stub
 * ui/Dockerfile, so no image is built and no network is used. Run with `npm test`.
 */
import { strict as assert } from 'node:assert';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, before, describe, it } from 'node:test';

import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';

import {
  CALLBACK_PATH,
  DOCKERFILE,
  FleetUiStack,
  SESSION_LENGTH,
  STACK_NAME,
  type UiSettings,
  readUiSettings,
  runtimeLocation,
} from '../lib/ui-stack';

const ACCOUNT = '123456789012';
const REGION = 'us-west-2';
const AGENT_ARN = `arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:runtime/fleetsupervisor_default_supervisor-AbCdEf1234`;
const FLEET_SECRET = `arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:fleet/neo4j-reader-AbC123`;

/** The settings deploy.sh exports from demos/aircraft-fleet/.env. */
const DEPLOY_ENV: Record<string, string> = {
  AGENT_ARN,
  NEO4J_URI: 'neo4j+s://fleet1234.databases.neo4j.io',
  NEO4J_USERNAME: 'neo4j',
  NEO4J_DATABASE: 'neo4j',
  NEO4J_PASSWORD_SECRET_ARN: FLEET_SECRET,
};

/** Files a real build context holds that must not reach the staged image context. */
const SECRET_FILES = ['.env', '.env.finance', 'supervisor-agent/.env.local', 'supervisor-agent/.mcp-credentials.json'];
const BULK_DIRS = ['supervisor-agent/.venv', 'ui/node_modules', 'ui/infra/cdk.out', 'pipeline/data', 'docs/images'];
const KEPT_FILES = [DOCKERFILE, 'ui/server.py', 'ui/package.json', 'ui/package-lock.json', 'ui/static/app.js', 'supervisor-agent/pyproject.toml'];

let imageContext: string;
let outdir: string;
let template: Template;

function writeFile(path: string, content: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

function synth(settings: UiSettings = readUiSettings(DEPLOY_ENV)): Template {
  const app = new App({ outdir });
  const stack = new FleetUiStack(app, STACK_NAME, { env: runtimeLocation(settings.agentArn), settings, imageContext });
  return Template.fromStack(stack);
}

before(() => {
  imageContext = mkdtempSync(join(tmpdir(), 'fleet-ui-context-'));
  outdir = mkdtempSync(join(tmpdir(), 'fleet-ui-cdk-out-'));
  writeFile(join(imageContext, DOCKERFILE), 'FROM scratch\n');
  for (const file of [...KEPT_FILES.slice(1), ...SECRET_FILES]) {
    writeFile(join(imageContext, file), 'stub\n');
  }
  for (const dir of BULK_DIRS) {
    writeFile(join(imageContext, dir, 'file'), 'stub\n');
  }
  template = synth();
});

after(() => {
  rmSync(imageContext, { recursive: true, force: true });
  rmSync(outdir, { recursive: true, force: true });
});

/** The logical ID of the only resource of this type. */
function onlyId(type: string): string {
  const ids = Object.keys(template.findResources(type));
  assert.equal(ids.length, 1, `expected one ${type}, found ${ids.length}`);
  return ids[0];
}

function functionEnv(): Record<string, unknown> {
  const [fn] = Object.values(template.findResources('AWS::Lambda::Function'));
  return fn.Properties.Environment.Variables;
}

/** Every logical ID that a value refers to through Ref or Fn::GetAtt. */
function references(value: unknown, found: Set<string> = new Set()): Set<string> {
  if (Array.isArray(value)) {
    value.forEach((item) => references(item, found));
  } else if (value !== null && typeof value === 'object') {
    for (const [key, inner] of Object.entries(value)) {
      if (key === 'Ref' && typeof inner === 'string') {
        found.add(inner);
      } else if (key === 'Fn::GetAtt') {
        found.add(Array.isArray(inner) ? String(inner[0]) : String(inner).split('.')[0]);
      } else {
        references(inner, found);
      }
    }
  }
  return found;
}

describe('function and URL', () => {
  it('serves the function URL with no IAM auth, in response stream mode', () => {
    template.resourceCountIs('AWS::Lambda::Url', 1);
    template.hasResourceProperties('AWS::Lambda::Url', {
      AuthType: 'NONE',
      InvokeMode: 'RESPONSE_STREAM',
      TargetFunctionArn: { 'Fn::GetAtt': [onlyId('AWS::Lambda::Function'), 'Arn'] },
    });
  });

  it('runs an arm64 container image that Lambda Web Adapter streams from', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      PackageType: 'Image',
      Architectures: ['arm64'],
    });
    assert.equal(functionEnv().AWS_LWA_INVOKE_MODE, 'response_stream');
  });

  it('runs longer than the stream reader waits for one read', () => {
    const [fn] = Object.values(template.findResources('AWS::Lambda::Function'));
    assert.ok(fn.Properties.Timeout > 300, `timeout ${fn.Properties.Timeout} s does not cover a 300 s read`);
    assert.ok(fn.Properties.Timeout <= 900);
  });

  it('gets the contract settings and no password, client ID, or reserved name', () => {
    const env = functionEnv();
    assert.deepEqual(Object.keys(env).sort(), [
      'AGENT_ARN',
      'AWS_LWA_INVOKE_MODE',
      'COGNITO_CLIENT_ID_PARAMETER',
      'COGNITO_DOMAIN',
      'COGNITO_USER_POOL_ID',
      'FLEET_SUPERVISOR_MODE',
      'FLEET_UI_AUTH',
      'NEO4J_DATABASE',
      'NEO4J_PASSWORD_SECRET_ARN',
      'NEO4J_URI',
      'NEO4J_USERNAME',
    ]);
    assert.equal(env.FLEET_UI_AUTH, 'cognito');
    assert.equal(env.FLEET_SUPERVISOR_MODE, 'cloud');
    assert.equal(env.AGENT_ARN, AGENT_ARN);
    assert.equal(env.NEO4J_PASSWORD_SECRET_ARN, FLEET_SECRET);
    assert.deepEqual(env.COGNITO_USER_POOL_ID, { Ref: onlyId('AWS::Cognito::UserPool') });
  });

  it('points COGNITO_DOMAIN at the managed login base URL', () => {
    const domain = JSON.stringify(functionEnv().COGNITO_DOMAIN);
    assert.match(domain, /"https:\/\/"/);
    assert.match(domain, new RegExp(`\\.auth\\.${REGION}\\.amazoncognito\\.com`));
    assert.ok(references(functionEnv().COGNITO_DOMAIN).has(onlyId('AWS::Cognito::UserPoolDomain')));
    template.hasResourceProperties('AWS::Cognito::UserPoolDomain', { Domain: `fleet-ui-${ACCOUNT}` });
  });

  it('deploys in the region and account of the runtime', () => {
    assert.deepEqual(runtimeLocation(AGENT_ARN), { region: REGION, account: ACCOUNT });
  });
});

describe('role', () => {
  /** Each action and resource pair the role's policies allow. */
  function allowed(): string[] {
    const roleId = onlyId('AWS::IAM::Role');
    const pairs: string[] = [];
    for (const policy of Object.values(template.findResources('AWS::IAM::Policy'))) {
      assert.deepEqual(policy.Properties.Roles, [{ Ref: roleId }], 'a policy attaches to another role');
      for (const statement of policy.Properties.PolicyDocument.Statement) {
        assert.equal(statement.Effect, 'Allow');
        assert.equal(statement.Condition, undefined);
        for (const action of [statement.Action].flat()) {
          for (const resource of [statement.Resource].flat()) {
            pairs.push(`${action} ${JSON.stringify(resource)}`);
          }
        }
      }
    }
    return pairs.sort();
  }

  it('is assumed only by Lambda and has no managed policies', () => {
    const [role] = Object.values(template.findResources('AWS::IAM::Role'));
    assert.equal(role.Properties.ManagedPolicyArns, undefined);
    assert.deepEqual(role.Properties.AssumeRolePolicyDocument.Statement, [
      { Action: 'sts:AssumeRole', Effect: 'Allow', Principal: { Service: 'lambda.amazonaws.com' } },
    ]);
  });

  it('can invoke the runtime, read the fleet login and client ID, and write its logs, and nothing else', () => {
    const logs = { 'Fn::GetAtt': [onlyId('AWS::Logs::LogGroup'), 'Arn'] };
    const parameter = {
      'Fn::Join': ['', ['arn:', { Ref: 'AWS::Partition' }, `:ssm:${REGION}:${ACCOUNT}:parameter/fleet-ui/${STACK_NAME}/cognito-client-id`]],
    };
    assert.deepEqual(
      allowed(),
      [
        `bedrock-agentcore:InvokeAgentRuntime ${JSON.stringify(AGENT_ARN)}`,
        `bedrock-agentcore:InvokeAgentRuntime ${JSON.stringify(`${AGENT_ARN}/runtime-endpoint/DEFAULT`)}`,
        `logs:CreateLogStream ${JSON.stringify(logs)}`,
        `logs:PutLogEvents ${JSON.stringify(logs)}`,
        `secretsmanager:GetSecretValue ${JSON.stringify(FLEET_SECRET)}`,
        `ssm:GetParameter ${JSON.stringify(parameter)}`,
      ].sort(),
    );
  });
});

describe('Cognito', () => {
  it('lets only an admin create users', () => {
    template.hasResourceProperties('AWS::Cognito::UserPool', {
      AdminCreateUserConfig: { AllowAdminCreateUserOnly: true },
    });
  });

  it('has one public app client with the code flow and no secret', () => {
    template.resourceCountIs('AWS::Cognito::UserPoolClient', 1);
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      GenerateSecret: false,
      AllowedOAuthFlows: ['code'],
      AllowedOAuthFlowsUserPoolClient: true,
      AllowedOAuthScopes: ['openid'],
      SupportedIdentityProviders: ['COGNITO'],
    });
  });

  it('sets the session length through the ID token lifetime', () => {
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      IdTokenValidity: SESSION_LENGTH.toMinutes(),
      TokenValidityUnits: Match.objectLike({ IdToken: 'minutes' }),
    });
  });

  it('calls back to the function URL plus auth/callback, and signs out to the function URL', () => {
    const url = { 'Fn::GetAtt': [onlyId('AWS::Lambda::Url'), 'FunctionUrl'] };
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      CallbackURLs: [{ 'Fn::Join': ['', [url, CALLBACK_PATH]] }],
      LogoutURLs: [url],
    });
  });

  it('removes the user pool with the stack', () => {
    template.hasResource('AWS::Cognito::UserPool', { DeletionPolicy: 'Delete', UpdateReplacePolicy: 'Delete' });
  });
});

describe('client ID parameter', () => {
  it('holds the app client ID under the name the function gets', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Type: 'String',
      Name: `/fleet-ui/${STACK_NAME}/cognito-client-id`,
      Value: { Ref: onlyId('AWS::Cognito::UserPoolClient') },
    });
    assert.equal(functionEnv().COGNITO_CLIENT_ID_PARAMETER, `/fleet-ui/${STACK_NAME}/cognito-client-id`);
  });

  it('leaves the function with no reference to the client or the parameter', () => {
    const [fn] = Object.values(template.findResources('AWS::Lambda::Function'));
    const refs = references(fn);
    assert.ok(!refs.has(onlyId('AWS::Cognito::UserPoolClient')));
    assert.ok(!refs.has(onlyId('AWS::SSM::Parameter')));
  });

  it('synthesizes a template with no dependency cycle', () => {
    const resources: Record<string, { DependsOn?: string | string[] }> = template.toJSON().Resources;
    const edges = new Map<string, string[]>();
    for (const [id, resource] of Object.entries(resources)) {
      const deps = [...references(resource), ...[resource.DependsOn ?? []].flat()];
      edges.set(id, deps.filter((dep) => dep in resources));
    }
    const done = new Set<string>();
    const visit = (id: string, path: string[]): void => {
      if (path.includes(id)) {
        assert.fail(`dependency cycle: ${[...path.slice(path.indexOf(id)), id].join(' -> ')}`);
      }
      if (done.has(id)) {
        return;
      }
      for (const dep of edges.get(id) ?? []) {
        visit(dep, [...path, id]);
      }
      done.add(id);
    };
    for (const id of edges.keys()) {
      visit(id, []);
    }
  });
});

describe('image context', () => {
  /** The staged copy of the build context in cdk.out. */
  function stagedContext(): string {
    const assets = JSON.parse(readFileSync(join(outdir, `${STACK_NAME}.assets.json`), 'utf-8'));
    const images = Object.values(assets.dockerImages) as { source: { directory: string; dockerFile?: string } }[];
    assert.equal(images.length, 1);
    assert.equal(images[0].source.dockerFile, DOCKERFILE);
    return join(outdir, images[0].source.directory);
  }

  it('keeps the files the image build reads', () => {
    for (const file of KEPT_FILES) {
      assert.ok(existsSync(join(stagedContext(), file)), `${file} is missing from the build context`);
    }
  });

  it('leaves secrets and bulk folders out of the staged build context', () => {
    for (const path of [...SECRET_FILES, ...BULK_DIRS]) {
      assert.ok(!existsSync(join(stagedContext(), path)), `${path} was copied into cdk.out`);
    }
    assert.deepEqual(readdirSync(stagedContext()).sort(), ['supervisor-agent', 'ui']);
  });
});

describe('image context with a .dockerignore allowlist', () => {
  /**
   * The same shape as demos/aircraft-fleet/.dockerignore: leave everything out, then let in
   * only what the image is built from. CDK stages the context from these rules, and its own
   * "!Dockerfile" rule matches only a Dockerfile at the context root, so ui/Dockerfile must be
   * listed.
   */
  const DOCKERIGNORE = [
    '*',
    `!${DOCKERFILE}`,
    '!supervisor-agent/pyproject.toml',
    '!ui/server.py',
    '!ui/static/',
    '**/.env*',
  ].join('\n');

  let allowlistContext: string;
  let allowlistOutdir: string;
  let staged: string;

  before(() => {
    allowlistContext = mkdtempSync(join(tmpdir(), 'fleet-ui-allowlist-context-'));
    allowlistOutdir = mkdtempSync(join(tmpdir(), 'fleet-ui-allowlist-cdk-out-'));
    writeFile(join(allowlistContext, '.dockerignore'), `${DOCKERIGNORE}\n`);
    writeFile(join(allowlistContext, DOCKERFILE), 'FROM scratch\n');
    for (const file of ['supervisor-agent/pyproject.toml', 'ui/server.py', 'ui/static/app.js', '.env', 'ui/.env']) {
      writeFile(join(allowlistContext, file), 'stub\n');
    }
    const settings = readUiSettings(DEPLOY_ENV);
    const app = new App({ outdir: allowlistOutdir });
    new FleetUiStack(app, STACK_NAME, { env: runtimeLocation(settings.agentArn), settings, imageContext: allowlistContext });
    app.synth();
    const assets = JSON.parse(readFileSync(join(allowlistOutdir, `${STACK_NAME}.assets.json`), 'utf-8'));
    const [image] = Object.values(assets.dockerImages) as { source: { directory: string } }[];
    staged = join(allowlistOutdir, image.source.directory);
  });

  after(() => {
    rmSync(allowlistContext, { recursive: true, force: true });
    rmSync(allowlistOutdir, { recursive: true, force: true });
  });

  it('stages ui/Dockerfile and the allowed files', () => {
    for (const file of [DOCKERFILE, 'supervisor-agent/pyproject.toml', 'ui/server.py', 'ui/static/app.js']) {
      assert.ok(existsSync(join(staged, file)), `${file} is missing from the staged build context`);
    }
  });

  it('leaves .env out of the staged build context', () => {
    for (const file of ['.env', 'ui/.env']) {
      assert.ok(!existsSync(join(staged, file)), `${file} was copied into cdk.out`);
    }
  });
});

describe('readUiSettings', () => {
  function problems(env: Record<string, string | undefined>): string {
    try {
      readUiSettings({ ...DEPLOY_ENV, ...env });
    } catch (error) {
      return (error as Error).message;
    }
    assert.fail('the settings were accepted');
  }

  it('reads the five settings', () => {
    assert.deepEqual(readUiSettings(DEPLOY_ENV), {
      agentArn: AGENT_ARN,
      neo4jUri: DEPLOY_ENV.NEO4J_URI,
      neo4jUsername: 'neo4j',
      neo4jDatabase: 'neo4j',
      neo4jPasswordSecretArn: FLEET_SECRET,
    });
  });

  it('names every missing setting in one error', () => {
    const message = problems({ AGENT_ARN: undefined, NEO4J_PASSWORD_SECRET_ARN: '  ' });
    assert.match(message, /AGENT_ARN is not set/);
    assert.match(message, /NEO4J_PASSWORD_SECRET_ARN is not set/);
    assert.match(message, /demos\/aircraft-fleet\/\.env/);
  });

  it('refuses an endpoint ARN in place of the runtime ARN', () => {
    assert.match(problems({ AGENT_ARN: `${AGENT_ARN}/runtime-endpoint/DEFAULT` }), /AGENT_ARN is not an AgentCore runtime ARN/);
  });

  it('refuses a URI without TLS and a secret ARN without its suffix', () => {
    const message = problems({
      NEO4J_URI: 'neo4j://fleet1234.databases.neo4j.io',
      NEO4J_PASSWORD_SECRET_ARN: `arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:fleetreader`,
    });
    assert.match(message, /NEO4J_URI must be neo4j\+s/);
    assert.match(message, /not a complete Secrets Manager secret ARN/);
  });

  it('refuses a secret in another region than the runtime', () => {
    const elsewhere = FLEET_SECRET.replace(REGION, 'us-east-1');
    assert.match(problems({ NEO4J_PASSWORD_SECRET_ARN: elsewhere }), /is in us-east-1, but the runtime and the UI are in us-west-2/);
  });
});
