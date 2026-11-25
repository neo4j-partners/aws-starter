"""Serve the fleet demo and relay a local or deployed supervisor's SSE stream."""

import hashlib
import json
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import AbstractContextManager, asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

# Import the supervisor package before TLS clients so it can set up truststore.
from fleet_supervisor.client.transport import stream_deployed, stream_local
from fleet_supervisor.core.config import ConfigError
from fleet_supervisor.core.graph.retrieval import RotatingLoginAuthManager, retry_on_rotated_login

# isort: split

import httpx
import urllib3.exceptions
import uvicorn
from auth import RequireLogin, callback, load_login, login, logout, ready
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from evidence import load_evidence
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, StringConstraints, ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
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
    # Check the mode now, so a cloud mode with no ARN stops the UI at startup.
    supervisor_mode()
    # Check the login mode too, so a Cognito mode with a missing setting stops here.
    app.state.login = load_login()
    driver = None
    auth = None
    if uri := os.getenv("NEO4J_URI"):
        # The supervisor's graph tools use the same manager. A lookup that
        # Neo4j rejects reads the secret again through retry_on_rotated_login.
        auth = RotatingLoginAuthManager()
        try:
            # Read the login now, so a missing one turns evidence off at startup.
            auth.get_auth()
        except ConfigError as error:
            # The page still works without the evidence graph.
            logger.warning("Fleet graph evidence is off: %s", error)
            auth = None
        else:
            driver = GraphDatabase.driver(
                uri,
                auth=auth,
                connection_timeout=5,
                connection_acquisition_timeout=8,
                max_transaction_retry_time=0,
            )
    app.state.driver = driver
    app.state.auth = auth
    try:
        yield
    finally:
        if driver is not None:
            driver.close()


def supervisor_mode() -> str:
    """Return ``local`` or ``cloud`` from ``FLEET_SUPERVISOR_MODE``. Unset means local.

    The mode is explicit, so an ``AGENT_ARN`` in the shared .env does not move
    a local run to the cloud. Cloud mode needs ``AGENT_ARN``.
    """
    mode = os.getenv("FLEET_SUPERVISOR_MODE") or "local"
    if mode not in {"local", "cloud"}:
        raise ConfigError(f"FLEET_SUPERVISOR_MODE must be local or cloud, not {mode!r}.")
    if mode == "cloud" and not os.getenv("AGENT_ARN"):
        raise ConfigError(
            "FLEET_SUPERVISOR_MODE is cloud, but AGENT_ARN is not set. Deploy the "
            "supervisor with ./agent.sh deploy, or set AGENT_ARN in the shared .env."
        )
    return mode


def runtime_session_id(session_id: UUID, user_id: str | None) -> str:
    """Return the supervisor session ID for a browser session.

    With no user, it is the browser's ID, as local runs always sent. With a
    signed-in user, it is a hash of the user and the browser's ID, so one user
    who sends another user's session ID still gets a session of their own. Both
    forms meet the Runtime's 33-character minimum.
    """
    if user_id is None:
        return str(session_id)
    return hashlib.sha256(f"{user_id}\x00{session_id}".encode()).hexdigest()


def supervisor_stream(
    turn: ChatRequest, user_id: str | None
) -> AbstractContextManager[Iterator[dict[str, Any]]]:
    payload: dict[str, Any] = {"prompt": turn.prompt, "trace": True}
    if user_id is not None:
        payload["user_id"] = user_id
    session_id = runtime_session_id(turn.session_id, user_id)
    if supervisor_mode() == "cloud":
        return stream_deployed(
            payload, os.environ["AGENT_ARN"], os.getenv("AWS_REGION"), session_id
        )
    port = os.getenv("AGENT_PORT", "7071")
    url = os.getenv("FLEET_SUPERVISOR_URL", f"http://127.0.0.1:{port}/invocations")
    return stream_local(payload, session_id, url)


def _frame(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def relay(
    turn: ChatRequest,
    driver: Driver | None,
    auth: RotatingLoginAuthManager | None,
    user_id: str | None = None,
) -> Iterator[str]:
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    terminal = False
    try:
        with supervisor_stream(turn, user_id) as events:
            for event in events:
                if event.get("type") == "tool_complete":
                    ids = event.pop("evidence_ids", [])
                    if ids and driver is not None and auth is not None:
                        try:
                            event["graph"] = retry_on_rotated_login(
                                auth, partial(load_evidence, driver, database, ids)
                            )
                        except (ConfigError, DriverError, Neo4jError):
                            logger.exception("Fleet graph evidence lookup failed")
                            event["graph_unavailable"] = True
                        except Exception:
                            # Any other lookup failure, such as a node with no ID,
                            # costs only the graph. The answer keeps streaming.
                            logger.error("Fleet graph evidence could not be built", exc_info=True)
                            event["graph_unavailable"] = True
                    elif ids:
                        event["graph_unavailable"] = True
                yield _frame(event)
                if event.get("type") in {"complete", "error"}:
                    terminal = True
                    break
    except (httpx.HTTPError, urllib3.exceptions.HTTPError, BotoCoreError, ClientError):
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
    # RequireLogin sets the Cognito user. With no login, there is none.
    user_id = getattr(request.state, "user_id", None)
    return StreamingResponse(
        relay(turn, request.app.state.driver, request.app.state.auth, user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def index(_request: Request) -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/auth/login", login),
        Route("/auth/callback", callback),
        Route("/auth/logout", logout),
        Route("/ready", ready),
        Mount("/static", StaticFiles(directory=ROOT / "static")),
    ],
    middleware=[Middleware(RequireLogin)],
    lifespan=lifespan,
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("FLEET_UI_PORT", "8081")))
