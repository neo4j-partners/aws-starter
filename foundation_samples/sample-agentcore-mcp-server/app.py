#!/usr/bin/env python3
"""CDK App entry point for Sample Two MCP Server on AgentCore."""
import aws_cdk as cdk
from sample_two_stack import SampleTwoStack

app = cdk.App()
SampleTwoStack(app, "SampleTwoMCPServer")

app.synth()
