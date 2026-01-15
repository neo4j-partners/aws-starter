#!/usr/bin/env python3
"""
Simple OAuth2 M2M Demo - CDK App Entry Point

This app deploys the SimpleOAuthStack which demonstrates OAuth2 client
credentials (M2M) authentication with AgentGateway and Cognito.
"""

import aws_cdk as cdk
from simple_oauth_stack import SimpleOAuthStack

app = cdk.App()
SimpleOAuthStack(app, "SimpleOAuthDemo")

app.synth()
