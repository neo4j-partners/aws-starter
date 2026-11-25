#!/usr/bin/env node
import { join } from 'node:path';

import { App } from 'aws-cdk-lib';

import { FleetUiStack, STACK_NAME, readUiSettings, runtimeLocation } from '../lib/ui-stack';

try {
  const settings = readUiSettings(process.env);
  const app = new App();
  new FleetUiStack(app, STACK_NAME, {
    // The UI deploys to the runtime's account and region. deploy.sh checks that the active
    // credentials belong to that account.
    env: runtimeLocation(settings.agentArn),
    description: 'Aircraft fleet UI on Lambda with a streaming function URL and Cognito sign-in',
    settings,
    // This file runs as ui/infra/dist/bin/app.js. The build context is demos/aircraft-fleet/.
    imageContext: join(__dirname, '..', '..', '..', '..'),
  });
  app.synth();
} catch (error) {
  console.error('Fleet UI synthesis failed:', error instanceof Error ? error.message : error);
  process.exit(1);
}
