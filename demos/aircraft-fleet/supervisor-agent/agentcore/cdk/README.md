# AgentCore CDK app

This CDK app is managed by the AgentCore CLI. It deploys everything declared in `agentcore/agentcore.json` into AWS
through the `@aws/agentcore-cdk` constructs. The app has these files:

- `bin/cdk.ts`: The entry point. It reads the project once (`readAgentCoreProject`), creates one stack per deployment
  target (`resolveTargetStacks`), and turns `agentcore.json` into the application's props (`transformAgentCoreJson`).
  Everything about how `agentcore.json` is interpreted lives in the library, so it changes with the library version, not
  with this file.
- `lib/cdk-stack.ts`: `AgentCoreStack` instantiates one `AgentCoreApplication`. It then adds the fleet graph and memory
  settings to the `supervisor` Runtime and grants its role read access to the two password secrets. This is the file you
  edit.
- `test/cdk-stack.test.ts`: The synth tests for the stack's deploy settings and secret grants. `npm test` runs them.
- `cdk.json`: The CDK CLI config. It runs the compiled entry point, `dist/bin/cdk.js`.
- `package.json` and `package-lock.json`: The npm dependencies and the `build` and `test` scripts.
- `tsconfig.json`: The TypeScript compiler settings.

Harness settings are read from `harness.yaml`. Inline `systemPrompt` text overrides
the conventional `system-prompt.md` file in the harness directory.

## The CLI runs it for you

You normally do not run this app directly:

```bash
agentcore build    # synthesizes the CloudFormation templates into agentcore/cdk/cdk.out
agentcore deploy   # synthesizes, then deploys the stack for the selected target
agentcore status   # reports the resources agentcore.json declares
```

`npm run build` compiles the app, and `npx cdk synth` / `npx cdk diff` work from this directory too.

## Extending the stack

Add your own AWS resources in `lib/cdk-stack.ts` after the application and wire them to a runtime or harness through the
application's accessors. Runtimes and harnesses implement `iam.IGrantable`, so any AWS L2 grant accepts them. They
expose `grantRead` / `grantWrite` / `grantReadWrite` for DynamoDB tables and S3 buckets. A Secrets Manager secret takes
only `grantRead`, because `grantWrite` and `grantReadWrite` throw on a secret. They also expose
`grant(actions, resources)` and `addEnvironmentVariable`, which the example uses:

```ts
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';

const orders = new dynamodb.Table(this, 'Orders', {
  partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
});
const runtime = this.application.runtimes.get(RUNTIME_NAME);
if (runtime !== undefined) {
  runtime.grant(['dynamodb:GetItem', 'dynamodb:PutItem'], [orders.tableArn]); // updates the runtime's execution role
  runtime.addEnvironmentVariable('ORDERS_TABLE', orders.tableName);
}
```

Then run `./agent.sh deploy` again. `runtimes.get` returns `undefined` for a name that `agentcore.json` does not declare.
The stack checks for that case. `agent.sh destroy` removes the Runtime from the spec and deploys, so synth must still
pass with no Runtime.

If a runtime or harness is configured with an `executionRoleArn`, CDK cannot modify that imported role: every grant
emits a synth-time warning listing the permissions that were not attached, and the role must already carry them.

`agentcore status` reports only the resources `agentcore.json` declares; resources you add here are visible
through CloudFormation (`aws cloudformation describe-stack-resources`).
