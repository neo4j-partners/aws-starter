"""LangGraph multi-agent orchestrator graph.

Router classifies the query, then a conditional edge dispatches to one of two
specialist ReAct agents (maintenance or operations). Both specialists are
built by the same :func:`make_specialist_node` factory — they differ only by
name and system prompt.
"""

import logging
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent

from core.prompts import (
    MAINTENANCE_SYSTEM_PROMPT,
    OPERATIONS_SYSTEM_PROMPT,
    ROUTER_PROMPT,
)

logger = logging.getLogger(__name__)


class OrchestratorState(TypedDict):
    """State for the orchestrator graph."""

    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str  # Which agent to route to


def create_router_node(llm):
    """Create the router node that classifies queries."""

    async def router(state: OrchestratorState) -> dict:
        """Route the query to the appropriate specialist."""
        logger.info("[Router] Classifying query...")

        user_message = None
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                user_message = msg.content
                break

        if not user_message:
            return {"next_agent": "operations"}

        response = await llm.ainvoke(
            [
                {"role": "system", "content": ROUTER_PROMPT},
                {"role": "user", "content": user_message},
            ]
        )

        classification = response.content.strip().lower()
        logger.info("[Router] Classification: %s", classification)

        if "maintenance" in classification:
            return {"next_agent": "maintenance"}
        return {"next_agent": "operations"}

    return router


def make_specialist_node(name: str, llm, tools: list, prompt: str):
    """Create a specialist ReAct-agent node.

    ``name`` is used only for logging; maintenance and operations differ
    solely by ``prompt``.
    """
    agent = create_react_agent(llm, tools, prompt=prompt)

    async def specialist_node(state: OrchestratorState) -> dict:
        logger.info("[%s Agent] Processing query...", name)
        result = await agent.ainvoke({"messages": state["messages"]})
        logger.info("[%s Agent] Done", name)
        return {"messages": result["messages"]}

    return specialist_node


def route_to_agent(state: OrchestratorState) -> Literal["maintenance", "operations"]:
    """Conditional edge function to route to the correct agent."""
    return state["next_agent"]


async def create_orchestrator_graph(llm, tools):
    """Create the multi-agent orchestrator graph."""
    logger.info("Creating orchestrator graph...")

    graph = StateGraph(OrchestratorState)

    graph.add_node("router", create_router_node(llm))
    graph.add_node(
        "maintenance",
        make_specialist_node("Maintenance", llm, tools, MAINTENANCE_SYSTEM_PROMPT),
    )
    graph.add_node(
        "operations",
        make_specialist_node("Operations", llm, tools, OPERATIONS_SYSTEM_PROMPT),
    )

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        route_to_agent,
        {"maintenance": "maintenance", "operations": "operations"},
    )
    graph.add_edge("maintenance", END)
    graph.add_edge("operations", END)

    memory = MemorySaver()
    compiled = graph.compile(checkpointer=memory)

    logger.info("Orchestrator graph created: Router -> [Maintenance | Operations]")
    return compiled
