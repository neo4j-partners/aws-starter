import { CfnOutput, Duration, RemovalPolicy, Stack, type StackProps } from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';

/** The stack name that deploy.sh deploys, checks, and deletes. */
export const STACK_NAME = 'FleetUi';

/** The app's OAuth routes. It builds its redirect URI as https://{host}/auth/callback. */
export const CALLBACK_PATH = 'auth/callback';

/**
 * The image build file and the paths the build leaves out, both relative to the build context,
 * demos/aircraft-fleet/. CDK copies the context into cdk.out before Docker builds it, so these
 * also keep secrets out of that copy. ui/infra holds this app and its cdk.out, which would
 * otherwise copy into itself.
 */
export const DOCKERFILE = 'ui/Dockerfile';
export const IMAGE_EXCLUDES = [
  '**/.env',
  '**/.env.*',
  '**/.mcp-credentials*.json',
  '**/.venv',
  '**/node_modules',
  '**/__pycache__',
  '**/.pytest_cache',
  'ui/infra',
  'pipeline',
  'docs',
  'supervisor-agent/agentcore',
];

/**
 * The function's time limit, the Lambda maximum. The stream reader waits up to 300 seconds for
 * each read, so one answer can run longer than 300 seconds in total.
 */
export const FUNCTION_TIMEOUT = Duration.minutes(15);
export const MEMORY_MB = 2048;

/** The app client's ID token lifetime. The app's session is the ID token, so a sign-in lasts this long. */
export const SESSION_LENGTH = Duration.hours(1);

/** The settings the function gets from demos/aircraft-fleet/.env. */
export interface UiSettings {
  /** The supervisor runtime ARN that `./agent.sh deploy` writes. */
  readonly agentArn: string;
  readonly neo4jUri: string;
  readonly neo4jUsername: string;
  readonly neo4jDatabase: string;
  /** The read-only fleet login secret. The function reads it at startup. */
  readonly neo4jPasswordSecretArn: string;
}

const SETTING_VARS = {
  agentArn: 'AGENT_ARN',
  neo4jUri: 'NEO4J_URI',
  neo4jUsername: 'NEO4J_USERNAME',
  neo4jDatabase: 'NEO4J_DATABASE',
  neo4jPasswordSecretArn: 'NEO4J_PASSWORD_SECRET_ARN',
} as const satisfies Record<keyof UiSettings, string>;

/** The same runtime ARN format agent.sh reads from `agentcore status`. An endpoint ARN does not match. */
const RUNTIME_ARN = /^arn:aws[a-z0-9-]*:bedrock-agentcore:([a-z0-9-]+):(\d{12}):runtime\/[^/]+$/;
/** The whole value must be scheme://host with an optional port. The cloud path must use TLS. */
const TLS_NEO4J_URI = /^(neo4j|bolt)\+s:\/\/[A-Za-z0-9.-]+(:\d{1,5})?$/;
/** A complete secret ARN ends in the six-character suffix Secrets Manager adds. */
const COMPLETE_SECRET_ARN = /^arn:aws[a-z-]*:secretsmanager:([a-z0-9-]+):\d{12}:secret:.+-[A-Za-z0-9]{6}$/;

/**
 * Read the UI settings from the deploy environment. deploy.sh exports them from
 * demos/aircraft-fleet/.env. Throws one error naming every missing or malformed setting, so
 * synth stops before anything is deployed.
 */
export function readUiSettings(env: NodeJS.ProcessEnv): UiSettings {
  const values: Partial<Record<keyof UiSettings, string>> = {};
  const problems: string[] = [];
  for (const [key, name] of Object.entries(SETTING_VARS) as [keyof UiSettings, string][]) {
    const value = env[name]?.trim();
    if (value) {
      values[key] = value;
    } else {
      problems.push(`${name} is not set`);
    }
  }
  const runtime = values.agentArn === undefined ? null : RUNTIME_ARN.exec(values.agentArn);
  if (values.agentArn !== undefined && runtime === null) {
    problems.push('AGENT_ARN is not an AgentCore runtime ARN (arn:aws:bedrock-agentcore:REGION:ACCOUNT:runtime/ID)');
  }
  if (values.neo4jUri !== undefined && !TLS_NEO4J_URI.test(values.neo4jUri)) {
    problems.push('NEO4J_URI must be neo4j+s://host or bolt+s://host, with an optional :port');
  }
  const secret = values.neo4jPasswordSecretArn === undefined ? null : COMPLETE_SECRET_ARN.exec(values.neo4jPasswordSecretArn);
  if (values.neo4jPasswordSecretArn !== undefined && secret === null) {
    problems.push('NEO4J_PASSWORD_SECRET_ARN is not a complete Secrets Manager secret ARN (it must end in the -XXXXXX suffix)');
  }
  if (runtime && secret && runtime[1] !== secret[1]) {
    problems.push(`NEO4J_PASSWORD_SECRET_ARN is in ${secret[1]}, but the runtime and the UI are in ${runtime[1]}`);
  }
  if (problems.length > 0) {
    throw new Error(
      `Missing or invalid UI deploy settings:\n  - ${problems.join('\n  - ')}\n` +
        'Fix them in demos/aircraft-fleet/.env and deploy with ui/deploy.sh deploy.',
    );
  }
  return values as UiSettings;
}

/** The region and account that a runtime ARN names. The UI deploys next to its runtime. */
export function runtimeLocation(agentArn: string): { region: string; account: string } {
  const match = RUNTIME_ARN.exec(agentArn);
  if (match === null) {
    throw new Error(`Not an AgentCore runtime ARN: ${agentArn}`);
  }
  return { region: match[1], account: match[2] };
}

export interface FleetUiStackProps extends StackProps {
  readonly settings: UiSettings;
  /** The image build context, demos/aircraft-fleet/. */
  readonly imageContext: string;
}

/**
 * The hosted fleet UI: a container image function behind a streaming function URL, a Cognito
 * user pool that admins fill, and a role that can call only the fleet runtime and read only
 * the fleet login.
 *
 * The app client needs the function URL for its callback, the URL needs the function, and the
 * app needs the client ID. So the function gets the name of an SSM parameter, not the ID, and
 * the parameter holds the ID. Nothing then points back to the function: the URL refers to the
 * function, the client to the URL, and the parameter to the client.
 */
export class FleetUiStack extends Stack {
  /** The SSM parameter that holds the app client ID. */
  public readonly clientIdParameterName: string;

  constructor(scope: Construct, id: string, props: FleetUiStackProps) {
    super(scope, id, props);
    const { settings } = props;
    this.clientIdParameterName = `/fleet-ui/${this.stackName}/cognito-client-id`;

    const users = new cognito.UserPool(this, 'Users', {
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    // A Cognito domain prefix is unique per region, so the account ID keeps it from clashing.
    const domain = users.addDomain('Domain', {
      cognitoDomain: { domainPrefix: `fleet-ui-${this.account}` },
    });

    const logGroup = new logs.LogGroup(this, 'Logs', {
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // No managed policies. Every statement below names its resource.
    const role = new iam.Role(this, 'Role', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Fleet UI: invoke the fleet runtime, read the fleet login and the app client ID, and write logs',
    });
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        // IAM checks both the runtime and the endpoint. The client always calls DEFAULT.
        resources: [settings.agentArn, `${settings.agentArn}/runtime-endpoint/DEFAULT`],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['secretsmanager:GetSecretValue'],
        resources: [settings.neo4jPasswordSecretArn],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ssm:GetParameter'],
        // Built from the literal name, not the parameter resource, so the role does not
        // depend on the client.
        resources: [`arn:${this.partition}:ssm:${this.region}:${this.account}:parameter${this.clientIdParameterName}`],
      }),
    );
    logGroup.grantWrite(role);

    const fn = new lambda.DockerImageFunction(this, 'Function', {
      description: 'Aircraft fleet UI, run by Lambda Web Adapter',
      code: lambda.DockerImageCode.fromImageAsset(props.imageContext, {
        file: DOCKERFILE,
        platform: Platform.LINUX_ARM64,
        exclude: IMAGE_EXCLUDES,
      }),
      architecture: lambda.Architecture.ARM_64,
      memorySize: MEMORY_MB,
      timeout: FUNCTION_TIMEOUT,
      role,
      logGroup,
      // Lambda sets AWS_REGION itself, to the stack's region, which is the runtime's region.
      environment: {
        AWS_LWA_INVOKE_MODE: 'response_stream',
        FLEET_UI_AUTH: 'cognito',
        COGNITO_USER_POOL_ID: users.userPoolId,
        COGNITO_CLIENT_ID_PARAMETER: this.clientIdParameterName,
        COGNITO_DOMAIN: domain.baseUrl(),
        FLEET_SUPERVISOR_MODE: 'cloud',
        AGENT_ARN: settings.agentArn,
        NEO4J_URI: settings.neo4jUri,
        NEO4J_USERNAME: settings.neo4jUsername,
        NEO4J_DATABASE: settings.neo4jDatabase,
        NEO4J_PASSWORD_SECRET_ARN: settings.neo4jPasswordSecretArn,
      },
    });

    // The app checks the Cognito session, so the URL itself is public.
    const functionUrl = fn.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
    });

    // The function URL ends in "/". Signing out returns to it.
    const client = users.addClient('WebClient', {
      generateSecret: false,
      preventUserExistenceErrors: true,
      supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID],
        callbackUrls: [`${functionUrl.url}${CALLBACK_PATH}`],
        logoutUrls: [functionUrl.url],
      },
      // The app's session is the verified ID token, so this is how long a sign-in lasts.
      idTokenValidity: SESSION_LENGTH,
    });

    new ssm.StringParameter(this, 'ClientIdParameter', {
      parameterName: this.clientIdParameterName,
      stringValue: client.userPoolClientId,
      description: 'The fleet UI app client ID, read by the UI function at startup',
    });

    new CfnOutput(this, 'UiUrl', { value: functionUrl.url, description: 'Open this URL to use the fleet UI' });
    new CfnOutput(this, 'UserPoolId', { value: users.userPoolId, description: 'deploy.sh add-user adds users here' });
    new CfnOutput(this, 'FunctionName', { value: fn.functionName });
  }
}
