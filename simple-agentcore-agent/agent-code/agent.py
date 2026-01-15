"""
Sample 1: Deploy Your First AI Agent to AgentCore Runtime

Matches the working CDK basic-runtime sample pattern exactly.
"""
from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


def create_agent() -> Agent:
    """Create a basic agent with simple functionality"""
    system_prompt = """You are a helpful assistant. Answer questions clearly and concisely."""
    return Agent(
        system_prompt=system_prompt,
        name="QuickStartAgent"
    )


@app.entrypoint
async def invoke(payload=None):
    """Main entrypoint for the agent"""
    try:
        # Get the query from payload
        query = payload.get("prompt", "Hello!") if payload else "Hello!"

        # Create and use the agent
        agent = create_agent()
        response = agent(query)

        return {
            "status": "success",
            "response": response.message['content'][0]['text']
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


if __name__ == "__main__":
    app.run()
