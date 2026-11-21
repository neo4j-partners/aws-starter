"""Supervisor memory in Neo4j, through neo4j-agent-memory.

Memory is required. These variables configure it:

- ``MEM_NEO4J_URI``, ``MEM_NEO4J_USERNAME``, and ``MEM_NEO4J_DATABASE`` name
  the memory database. It is a separate database from the fleet graph.
- ``MEM_NEO4J_PASSWORD_SECRET_ARN`` names a Secrets Manager secret in the
  cloud. ``MEM_NEO4J_PASSWORD`` holds the password itself for a local run.

The settings are built once per process. If Neo4j rejects the password,
:func:`forget_memory_settings` drops them so the next build reads the
password again. A request that failed with a password another request
already replaced leaves the newer settings in place.

One :class:`SharedMemory` holds the memory client and its event-loop thread
for the process. It opens on the first request. Each request gets a
:class:`MemorySession` with its own session manager on that client, and the
caller must close it when the request ends. A rejected password retires the
client. A retired client closes once its last session closes, on a
background thread, so no request waits for it. :func:`close_shared_memory`
closes every client at shutdown, and no request opens one after it starts.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from neo4j.exceptions import AuthError
from neo4j_agent_memory import MemorySettings
from neo4j_agent_memory.config.settings import ExtractionConfig, ExtractorType, Neo4jConfig
from neo4j_agent_memory.integrations.strands import (
    Neo4jRetrievalConfig,
    Neo4jSessionManager,
    SharedMemory,
)
from neo4j_agent_memory.llm.adapters.bedrock import BedrockEmbeddingProvider, BedrockProvider
from pydantic import SecretStr

from fleet_supervisor.core.config import AWS_REGION, ConfigError
from fleet_supervisor.core.secrets import forget_secrets, password_from

logger = logging.getLogger(__name__)

MEM_NEO4J_URI = "MEM_NEO4J_URI"

EMBEDDING_MODEL = "bedrock/amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024
# The model that extracts entities from stored messages. Sonnet 5.5 rejects
# a temperature and a forced toolChoice, so the extractor sends neither.
EXTRACTION_MODEL = "bedrock/global.anthropic.claude-sonnet-5-5"
# Only memories at least this similar to the question are added to it.
RETRIEVAL_MIN_SCORE = 0.75
# How long shutdown waits for open sessions before it closes the clients.
SESSION_WAIT_SECONDS = 30.0
# The longest SharedMemory.close() takes. It waits up to its default timeout
# of 30 s for background extraction, gives cancelled tasks the library's
# _SHUTDOWN_TIMEOUT_SECONDS of 5 s to unwind, then closes the driver within
# the default request_timeout of 30 s. The library does not export these, so
# they are restated here, and a test checks them against the library.
CLIENT_CLOSE_SECONDS = 30.0 + 5.0 + 30.0
# Time for the close's own thread work beyond those waits.
SHUTDOWN_MARGIN_SECONDS = 5.0
# The error a request gets when it needs a client after shutdown started.
SHUT_DOWN = "The memory clients are shut down."

# Called with a task name when background memory work starts. Returns the
# function to call when it ends.
BackgroundHook = Callable[[str], Callable[[], None]]


def memory_password() -> str:
    """Return the memory database password."""
    return password_from("MEM_NEO4J_PASSWORD_SECRET_ARN", "MEM_NEO4J_PASSWORD")


@dataclass
class _Build:
    """One settings build in progress, which concurrent callers wait on."""

    done: threading.Event = field(default_factory=threading.Event)
    settings: MemorySettings | None = None
    error: BaseException | None = None


# The settings built once per process, or None until the next build, and
# the build in progress, if any. Read and change both only under
# _settings_lock. The build itself runs outside the lock. A forget changes
# only built settings, so it never overlaps a build.
_settings: MemorySettings | None = None
_settings_build: _Build | None = None
_settings_lock = threading.Lock()


def forget_memory_settings(failed: MemorySettings) -> None:
    """Drop the cached settings and secrets if they still hold ``failed``'s password.

    Concurrent requests can fail with the same old password. The first one
    drops it, and the next build reads the password again. A later one finds
    the settings already dropped or rebuilt with another password, and keeps
    them. The shared client is retired the same way, if it opened with
    ``failed``'s password.
    """
    global _settings
    with _settings_lock:
        if _settings is not None and _same_password(_settings, failed):
            _settings = None
            forget_secrets()
    _retire_shared(failed)


def _password(settings: MemorySettings) -> str:
    return settings.neo4j.password.get_secret_value()


def _same_password(first: MemorySettings, second: MemorySettings) -> bool:
    """Compare two settings' passwords in constant time."""
    return hmac.compare_digest(_password(first).encode("utf-8"), _password(second).encode("utf-8"))


def password_rejected(error: BaseException) -> bool:
    """Return True if Neo4j rejected the credentials somewhere in ``error``'s chain.

    neo4j-agent-memory wraps the driver's ``AuthError`` in its own
    ``ConnectionError``, and Strands wraps that in a ``SessionException``.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, AuthError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def memory_settings() -> MemorySettings:
    """Return the memory settings, built once per process.

    Concurrent callers share one build. Each gets that build's settings or
    an error. The caller that built raises the build's error. Each other
    caller raises its own error, caused by the build's error, so no two
    threads add frames to one traceback. A waiter raises a ConfigError for
    a ConfigError and a RuntimeError for any other error, so only the
    caller that built sees the original type.

    Raises :class:`~fleet_supervisor.core.config.ConfigError` when
    ``MEM_NEO4J_URI`` or the password is missing, or the password secret
    cannot be read. A failure is not cached, so the next call builds again.
    """
    global _settings, _settings_build
    with _settings_lock:
        if _settings is not None:
            return _settings
        build = _settings_build
        if build is None:
            build = _settings_build = _Build()
            owner = True
        else:
            owner = False
    if not owner:
        build.done.wait()
        if isinstance(build.error, ConfigError):
            raise ConfigError(str(build.error)) from build.error
        if build.error is not None:
            raise RuntimeError("The memory settings build failed.") from build.error
        return build.settings
    try:
        build.settings = _build_memory_settings()
    except BaseException as error:
        # Every failure, even an interrupt, must reach the waiters.
        build.error = error
        raise
    finally:
        with _settings_lock:
            _settings = build.settings
            _settings_build = None
        build.done.set()
    return build.settings


def _build_memory_settings() -> MemorySettings:
    uri = os.environ.get(MEM_NEO4J_URI, "").strip()
    if not uri:
        raise ConfigError(f"{MEM_NEO4J_URI} is not set.")
    return MemorySettings(
        # Every value comes from here, never from a .env file.
        _env_file=None,
        # Set explicitly so a MEMORY_API_KEY in the environment cannot switch
        # the backend to the hosted service.
        backend="bolt",
        neo4j=Neo4jConfig(
            uri=uri,
            username=os.environ.get("MEM_NEO4J_USERNAME") or "neo4j",
            password=SecretStr(memory_password()),
            database=os.environ.get("MEM_NEO4J_DATABASE") or "neo4j",
        ),
        # Provider instances, so the region and dimensions are set here and
        # not left to package defaults.
        embedding=BedrockEmbeddingProvider(
            EMBEDDING_MODEL, aws_region=AWS_REGION, dimensions=EMBEDDING_DIMENSIONS
        ),
        llm=BedrockProvider(
            EXTRACTION_MODEL, aws_region=AWS_REGION, send_temperature=False, tool_choice="auto"
        ),
        # The default pipeline needs spaCy and GLiNER, which are not installed.
        extraction=ExtractionConfig(extractor_type=ExtractorType.LLM),
    )


@dataclass(eq=False)
class _Shared:
    """A shared client, the settings it opened with, and its open sessions.

    Change ``open_sessions``, ``retired`` and ``closing`` only under
    ``_shared_lock``.
    """

    memory: SharedMemory
    settings: MemorySettings
    open_sessions: int = 0
    retired: bool = False
    closing: bool = False


@dataclass
class _Open:
    """One open of the shared client in progress, which concurrent callers wait on."""

    settings: MemorySettings
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


class MemoryClientError(RuntimeError):
    """A failure on a shared client, with the settings that client used.

    The settings may belong to another request. The failure is the cause.
    """

    def __init__(self, message: str, settings: MemorySettings) -> None:
        super().__init__(message)
        self.settings = settings


class SharedMemoryOpenError(MemoryClientError):
    """The shared client failed to open."""

    def __init__(self, settings: MemorySettings) -> None:
        super().__init__("Opening the shared memory client failed.", settings)


class MemorySessionError(MemoryClientError):
    """A session on the shared client failed, after the client opened."""

    def __init__(self, settings: MemorySettings) -> None:
        super().__init__("A memory session on the shared client failed.", settings)


# The client new sessions use, or None until the next open. The open in
# progress, if any. Retired clients that still have open sessions. The
# threads closing retired clients. Whether shutdown has started. Read and
# change all five only under _shared_lock, which _sessions_closed also uses.
_shared: _Shared | None = None
_shared_open: _Open | None = None
_retired: set[_Shared] = set()
_closers: set[threading.Thread] = set()
_shutting_down = False
_shared_lock = threading.Lock()
_sessions_closed = threading.Condition(_shared_lock)


class MemorySession:
    """One request's session manager on the shared memory client.

    Call ``close()`` once when the request ends, on every path. It writes the
    manager's messages, then releases the request's hold on the client.
    """

    def __init__(self, manager: Neo4jSessionManager, shared: _Shared) -> None:
        self.manager = manager
        self._shared = shared
        self._released = False

    @property
    def settings(self) -> MemorySettings:
        """The settings the session's client opened with."""
        return self._shared.settings

    def close(self) -> None:
        """Close the manager, then release the client, even if the close fails."""
        try:
            self.manager.close()
        finally:
            if not self._released:
                self._released = True
                _release(self._shared)


def build_session_manager(
    session_id: str,
    user_id: str,
    settings: MemorySettings,
    background_hook: BackgroundHook | None,
) -> MemorySession:
    """Return the memory session for one request, on the shared client.

    The first call opens the shared client with ``settings`` and
    ``background_hook``. Later calls use that client. Entity extraction runs
    after each write, in the background, and ``background_hook`` reports it.
    The manager restores the session history when the agent that owns it is
    built. The caller must call ``close()`` when the request ends, on every
    path.

    Raises :class:`SharedMemoryOpenError` when the shared client cannot
    open, and a RuntimeError once shutdown has started.
    """
    shared = _acquire(settings, background_hook)
    try:
        manager = shared.memory.session_manager(
            session_id,
            user_id=user_id,
            retrieval_config=Neo4jRetrievalConfig(min_score=RETRIEVAL_MIN_SCORE),
            # Set explicitly, because defaults can change between releases.
            extract_entities=True,
            defer_extraction=True,
            record_tool_calls=False,
        )
    except BaseException:
        _release(shared)
        raise
    return MemorySession(manager, shared)


def _acquire(settings: MemorySettings, background_hook: BackgroundHook | None) -> _Shared:
    """Return the shared client with one more open session, opening it if needed.

    Concurrent callers share one open. A caller with the same password as
    a failed open shares its failure. A caller with another password opens
    again with its own. A failed open is not cached, so the next call opens
    again. Once shutdown starts, no call opens a client.
    """
    global _shared, _shared_open
    while True:
        with _shared_lock:
            if _shutting_down:
                raise RuntimeError(SHUT_DOWN)
            if _shared is not None:
                _shared.open_sessions += 1
                return _shared
            opening = _shared_open
            if opening is None:
                opening = _shared_open = _Open(settings)
                break
        opening.done.wait()
        if opening.error is not None and _same_password(opening.settings, settings):
            raise SharedMemoryOpenError(opening.settings) from opening.error
        # The client opened, or failed with a password this caller no longer
        # uses. A rejected password may have retired the client already. So
        # look again.
    opened: _Shared | None = None
    late = False
    try:
        memory = SharedMemory.open(settings, background_hook=background_hook)
        opened = _Shared(memory, settings, open_sessions=1)
    except BaseException as error:
        # Every failure, even an interrupt, must reach the waiters.
        opening.error = error
        if isinstance(error, Exception):
            raise SharedMemoryOpenError(settings) from error
        raise
    finally:
        with _shared_lock:
            late = opened is not None and _shutting_down
            if not late:
                _shared = opened
                _shared_open = None
                # Wakes shutdown when the open failed while it waited.
                _sessions_closed.notify_all()
        try:
            if late:
                # Shutdown started during the open, so the client never goes
                # into use. Shutdown waits on the open while it closes, unless
                # the open outlasted the session wait. Then this close runs
                # after shutdown returns, on the request's daemon worker
                # thread, and the process may exit first. No session used the
                # client, so nothing is lost.
                _close_logged(opened)
        finally:
            if late:
                with _shared_lock:
                    _shared_open = None
                    _sessions_closed.notify_all()
            opening.done.set()
    if late:
        raise RuntimeError(SHUT_DOWN)
    return opened


def _release(shared: _Shared) -> None:
    """Drop one open session. Close a retired client when its last session closes."""
    with _shared_lock:
        shared.open_sessions -= 1
        _sessions_closed.notify_all()
        if not (shared.retired and shared.open_sessions == 0 and not shared.closing):
            return
        shared.closing = True
        _retired.discard(shared)
        _start_close(shared)


def _retire_shared(failed: MemorySettings) -> None:
    """Retire the current client if it opened with ``failed``'s password.

    New sessions then open a new client. The retired one closes when its
    last session closes, or at once when it has none.
    """
    global _shared
    with _shared_lock:
        shared = _shared
        if shared is None or not _same_password(shared.settings, failed):
            return
        _shared = None
        shared.retired = True
        if shared.open_sessions:
            _retired.add(shared)
            return
        shared.closing = True
        _start_close(shared)


def _start_close(shared: _Shared) -> None:
    """Close ``shared`` on its own thread, so the caller does not wait for it.

    Call it with ``_shared_lock`` held, in the same critical section that
    marks the client closing. Shutdown then finds the close in ``_closers``
    whenever it no longer finds the client, and never joins an unstarted
    thread.
    """
    closer = _closer(shared)
    _closers.add(closer)
    closer.start()


def _closer(shared: _Shared) -> threading.Thread:
    """Return an unstarted thread that closes ``shared``.

    A daemon, so a close that hangs past shutdown does not keep the process
    alive.
    """
    return threading.Thread(target=_close_logged, args=(shared,), name="memory-close", daemon=True)


def _close_logged(shared: _Shared) -> None:
    """Close a shared client, logging a failure.

    The close waits for the client's background work, such as entity
    extraction, before it closes the client.
    """
    try:
        shared.memory.close()
    except Exception:
        logger.exception("Error while closing the shared memory client")
    finally:
        with _shared_lock:
            _closers.discard(threading.current_thread())


def close_shared_memory() -> None:
    """Close the current client and every retired one still open. Blocks.

    From the start, no request opens a client. It waits up to
    ``SESSION_WAIT_SECONDS`` for an open in progress and for open sessions
    to close, since a session writes its messages on the client. Then it
    closes the clients anyway, in parallel, and waits for them and for
    closes already running. It returns within ``SESSION_WAIT_SECONDS`` plus
    ``CLIENT_CLOSE_SECONDS`` plus ``SHUTDOWN_MARGIN_SECONDS``, about 100
    seconds, and logs any close still running then.
    """
    global _shared, _shutting_down
    started = time.monotonic()
    session_deadline = started + SESSION_WAIT_SECONDS
    deadline = session_deadline + CLIENT_CLOSE_SECONDS + SHUTDOWN_MARGIN_SECONDS
    with _shared_lock:
        _shutting_down = True
        while True:
            clients = [shared for shared in (_shared, *_retired) if shared is not None]
            busy = _shared_open is not None or any(shared.open_sessions for shared in clients)
            if not busy or not _sessions_closed.wait(session_deadline - time.monotonic()):
                break
        # Counted again here, since the wait can end on its timeout.
        open_sessions = sum(shared.open_sessions for shared in clients)
        if open_sessions:
            logger.warning(
                "Closing the memory clients with %d memory session(s) still open after %ss.",
                open_sessions,
                SESSION_WAIT_SECONDS,
            )
        closing = [shared for shared in clients if not shared.closing]
        for shared in closing:
            shared.closing = True
        _shared = None
        _retired.clear()
        running = list(_closers)
    started_here = [_closer(shared) for shared in closing]
    for closer in started_here:
        closer.start()
    closers = running + started_here
    for closer in closers:
        closer.join(max(0.0, deadline - time.monotonic()))
    still_closing = sum(closer.is_alive() for closer in closers)
    if still_closing:
        logger.warning(
            "Shutdown stopped waiting after %.0fs with %d memory client close(s) still running.",
            deadline - started,
            still_closing,
        )
