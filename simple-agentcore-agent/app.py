#!/usr/bin/env python3
"""CDK App entry point for Sample One AgentCore Runtime."""
import aws_cdk as cdk
from sample_one_stack import SampleOneStack

app = cdk.App()
SampleOneStack(app, "SampleOneAgentDemo")

app.synth()
