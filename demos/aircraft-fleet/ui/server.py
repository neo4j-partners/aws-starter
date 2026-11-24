"""Serve the fleet demo and relay a local or deployed supervisor's SSE stream."""

import json
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, closing, contextmanager
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

# Import the supervisor package before TLS clients so it can set up truststore.
from fleet_supervisor.client.transport import (
    READ_TIMEOUT_S,
    RUNTIME_USER_ID,
    iter_events,
)
from fleet_supervisor.core.config import ConfigError
from fleet_supervisor.core.secrets import neo4j_login

# isort: split

import boto3
import httpx
import uvicorn
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from evidence import load_evidence
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, StringConstraints, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


class ChatRequest(BaseModel):
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    session_id: UUID


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    load_dotenv(os.environ.get("FLEET_ENV_FILE") or ROOT.parent / ".env")
    driver = None
    login = None
    if uri := os.getenv("NEO4J_URI"):
        try:
            login = neo4j_login()
        except ConfigError as error:
            # The page still works without the evidence graph.
            logger.warning("Fleet graph evidence is off: %s", error)
    if login:
        driver = GraphDatabase.driver(
            uri,
            auth=login,
            connection_timeout=5,
            connection_acquisition_timeout=8,
            max_transaction_retry_time=0,
        )
    app.state.driver = driver
    try:
        yield
    finally:
        if driver is not None:
            driver.close()


@contextmanager
def supervisor_stream(turn: ChatRequest) -> Iterator[Iterator[bytes]]:
    payload = {"prompt": turn.prompt, "trace": True}
    session_id = str(turn.session_id)
    if arn := os.getenv("AGENT_ARN"):
        client = boto3.client(
            "bedrock-agentcore",
            region_name=os.getenv("AWS_REGION"),
            config=Config(read_timeout=READ_TIMEOUT_S, connect_timeout=10),
        )
        with closing(client):
            response = client.invoke_agent_runtime(
                agentRuntimeArn=arn,
                runtimeSessionId=session_id,
                runtimeUserId=RUNTIME_USER_ID,
                payload=json.dumps(payload).encode(),
                qualifier="DEFAULT",
            )
            with closing(response["response"]) as body:
                yield body.iter_chunks()
        return

    port = os.getenv("AGENT_PORT", "7071")
    url = os.getenv("FLEET_SUPERVISOR_URL", f"http://127.0.0.1:{port}/invocations")
    with (
        httpx.Client(timeout=httpx.Timeout(READ_TIMEOUT_S, connect=10)) as client,
        client.stream(
            "POST",
            url,
            json=payload,
            headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id},
        ) as response,
    ):
        response.raise_for_status()
        yield response.iter_bytes()


def _frame(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def relay(turn: ChatRequest, driver: Driver | None) -> Iterator[str]:
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    terminal = False
    try:
        with supervisor_stream(turn) as chunks:
            for event in iter_events(chunks):
                if event.get("type") == "tool_complete":
                    ids = event.pop("evidence_ids", [])
                    if ids and driver is not None:
                        try:
                            event["graph"] = load_evidence(driver, database, ids)
                        except (DriverError, Neo4jError):
                            logger.exception("Fleet graph evidence lookup failed")
                            event["graph_unavailable"] = True
                    elif ids:
                        event["graph_unavailable"] = True
                yield _frame(event)
                if event.get("type") in {"complete", "error"}:
                    terminal = True
                    break
    except (httpx.HTTPError, BotoCoreError, ClientError):
        logger.exception("Fleet supervisor stream failed")
        yield _frame({"type": "error", "error": "Could not reach the fleet supervisor."})
        return
    if not terminal:
        yield _frame({"type": "error", "error": "The fleet supervisor closed the stream early."})


async def chat(request: Request) -> JSONResponse | StreamingResponse:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        return JSONResponse({"error": "Send the question as JSON."}, status_code=415)
    try:
        turn = ChatRequest.model_validate_json(await request.body())
    except ValidationError:
        return JSONResponse(
            {"error": "A valid session ID and a question are required."},
            status_code=400,
        )
    return StreamingResponse(
        relay(turn, request.app.state.driver),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def index(_request: Request) -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/chat", chat, methods=["POST"]),
        Mount("/static", StaticFiles(directory=ROOT / "static")),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("FLEET_UI_PORT", "8081")))
