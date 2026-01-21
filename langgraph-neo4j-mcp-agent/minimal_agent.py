#!/usr/bin/env python3
"""
Minimal LangGraph Agent for SageMaker Studio Testing

The simplest possible LangGraph agent to verify your environment works.
Uses AWS Bedrock Claude via langchain-aws.

Usage:
    python minimal_agent.py              # Run with default question
    python minimal_agent.py "question"   # Run with custom question
"""

import sys
from typing import Annotated, Literal

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode


# Simple tool for testing
@tool
def get_current_time() -> str:
    """Get the current date and time."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


# Define tools list
tools = [get_current_time, add_numbers]


def get_llm():
    """Initialize Bedrock Claude model."""
    return ChatBedrockConverse(
        model="us.anthropic.claude-sonnet-4-20250514-v1:0",
        region_name="us-west-2",
        temperature=0,
    ).bind_tools(tools)


def should_continue(state: MessagesState) -> Literal["tools", END]:
    """Determine whether to continue to tools or end."""
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END


def call_model(state: MessagesState):
    """Call the LLM."""
    llm = get_llm()
    messages = state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def build_graph():
    """Build the LangGraph agent."""
    # Create the graph
    graph = StateGraph(MessagesState)

    # Add nodes
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))

    # Add edges
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph.compile()


def run_agent(question: str):
    """Run the agent with a question."""
    print("=" * 60)
    print("Minimal LangGraph Agent")
    print("=" * 60)
    print()

    print("Building graph...")
    agent = build_graph()

    print(f"Question: {question}")
    print()
    print("Running agent...")
    print("-" * 60)

    result = agent.invoke({
        "messages": [
            SystemMessage(content="You are a helpful assistant. Use tools when needed."),
            HumanMessage(content=question),
        ]
    })

    # Print final response
    final_message = result["messages"][-1]
    print()
    print("Response:")
    print("-" * 60)
    print(final_message.content)
    print("-" * 60)

    return result


def main():
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = "What is the current time? Also, what is 42 + 17?"

    run_agent(question)


if __name__ == "__main__":
    main()
