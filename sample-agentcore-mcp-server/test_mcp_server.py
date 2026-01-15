#!/usr/bin/env python3
"""
Test script for deployed MCP server.
Uses the MCP Python client library to communicate with the server.
"""
import asyncio
import sys
import boto3
from datetime import timedelta
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def get_stack_outputs(stack_name: str = "SampleTwoMCPServer") -> dict:
    """Get outputs from CloudFormation stack."""
    cf = boto3.client("cloudformation")
    response = cf.describe_stacks(StackName=stack_name)

    outputs = {}
    for output in response["Stacks"][0]["Outputs"]:
        outputs[output["OutputKey"]] = output["OutputValue"]
    return outputs


def get_cognito_token(client_id: str, username: str, password: str) -> str:
    """Get JWT token from Cognito."""
    cognito = boto3.client("cognito-idp")

    response = cognito.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )

    return response["AuthenticationResult"]["AccessToken"]


async def test_mcp_server(runtime_arn: str, token: str, region: str):
    """Test the deployed MCP server."""
    # Encode the ARN for URL
    encoded_arn = runtime_arn.replace(":", "%3A").replace("/", "%2F")
    mcp_url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    headers = {
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print(f"Connecting to: {mcp_url[:80]}...")
    print()

    try:
        async with streamablehttp_client(
            mcp_url, headers, timeout=timedelta(seconds=120), terminate_on_close=False
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                print("Initializing MCP session...")
                await session.initialize()
                print("MCP session initialized\n")

                print("Listing available tools...")
                tool_result = await session.list_tools()

                print("\nAvailable MCP Tools:")
                print("=" * 50)
                for tool in tool_result.tools:
                    print(f"  {tool.name}: {tool.description}")

                print("\nTesting MCP Tools:")
                print("=" * 50)

                # Test add_numbers
                print("\nTesting add_numbers(5, 3)...")
                add_result = await session.call_tool(
                    name="add_numbers", arguments={"a": 5, "b": 3}
                )
                print(f"   Result: {add_result.content[0].text}")

                # Test multiply_numbers
                print("\nTesting multiply_numbers(4, 7)...")
                multiply_result = await session.call_tool(
                    name="multiply_numbers", arguments={"a": 4, "b": 7}
                )
                print(f"   Result: {multiply_result.content[0].text}")

                # Test greet_user
                print("\nTesting greet_user('Alice')...")
                greet_result = await session.call_tool(
                    name="greet_user", arguments={"name": "Alice"}
                )
                print(f"   Result: {greet_result.content[0].text}")

                # Test get_server_info
                print("\nTesting get_server_info()...")
                info_result = await session.call_tool(name="get_server_info", arguments={})
                print(f"   Result: {info_result.content[0].text}")

                print("\nMCP tool testing completed successfully!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def main():
    stack_name = sys.argv[1] if len(sys.argv) > 1 else "SampleTwoMCPServer"

    print(f"Getting stack outputs for {stack_name}...")

    try:
        outputs = get_stack_outputs(stack_name)
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the CDK stack is deployed: uv run cdk deploy")
        sys.exit(1)

    runtime_arn = outputs["MCPServerRuntimeArn"]
    client_id = outputs["CognitoClientId"]
    username = outputs["TestUsername"]
    password = outputs["TestPassword"]
    region = runtime_arn.split(":")[3]

    print(f"Runtime ARN: {runtime_arn}")
    print(f"Region: {region}")
    print()

    print("Getting Cognito token...")
    token = get_cognito_token(client_id, username, password)
    print("Token obtained successfully\n")

    asyncio.run(test_mcp_server(runtime_arn, token, region))


if __name__ == "__main__":
    main()
