#!/usr/bin/env python3
"""Generate bounded, synthetic traffic through the deployed Finance Agent.

Each request goes through the actual AgentCore or local runtime. The runtime
records user/assistant text and any MCP tool calls in NAMS, so this is useful
for populating realistic conversations and reasoning traces rather than merely
writing fixture rows.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import sys
import threading
import time
import uuid
from dataclasses import dataclass

from client.transport import Target, invoke


@dataclass(frozen=True)
class TrafficRequest:
    """One real agent invocation with a stable synthetic user/session scope."""

    number: int
    user_id: str
    session_id: str
    prompt: str


class ProgressReporter:
    """Serialize progress lines emitted by concurrent session workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def log(self, message: str) -> None:
        with self._lock:
            print(message, flush=True)


_PORTFOLIOS = (
    "low-volatility renewable-energy ETFs and a small semiconductor position",
    "municipal bonds, health-care dividend stocks, and no cryptocurrency",
    "a balanced index fund portfolio with modest exposure to regional banks",
    "cash-flow positive infrastructure companies and conservative bond funds",
)

_QUESTIONS = (
    "Which accounts have the highest risk scores, and where does their money flow?",
    "Find a suspicious circular transfer chain and explain the risk signal.",
    "Which communities have dense internal transfers but few merchant payments?",
    "Show high-betweenness accounts and why they are intermediaries.",
    "Find behaviorally similar high-risk accounts and shared counterparties.",
)


def build_requests(
    users: int,
    sessions_per_user: int,
    turns_per_session: int,
    run_id: str,
) -> list[TrafficRequest]:
    """Create varied synthetic conversations with predictable scopes."""
    requests: list[TrafficRequest] = []
    prompt_number = 0
    for user_number in range(users):
        user_id = f"nams-load-{run_id}-user-{user_number:04d}"
        portfolio = _PORTFOLIOS[user_number % len(_PORTFOLIOS)]
        for session_number in range(sessions_per_user):
            session_id = f"nams-load-{run_id}-u{user_number:04d}-s{session_number:03d}"
            for turn_number in range(turns_per_session):
                if turn_number == 0:
                    prompt = (
                        f"I am synthetic analyst {user_number:04d}. My simulated portfolio "
                        f"contains {portfolio}. Analyze the risk in that context, then investigate: "
                        f"{_QUESTIONS[prompt_number % len(_QUESTIONS)]}"
                    )
                else:
                    prompt = (
                        f"For synthetic analyst {user_number:04d}, continue the investigation. "
                        f"Focus on a different angle and cite the graph evidence: "
                        f"{_QUESTIONS[prompt_number % len(_QUESTIONS)]}"
                    )
                prompt_number += 1
                requests.append(
                    TrafficRequest(
                        number=len(requests) + 1,
                        user_id=user_id,
                        session_id=session_id,
                        prompt=prompt,
                    )
                )
    return requests


def _invoke(request: TrafficRequest, target: Target) -> tuple[TrafficRequest, dict, float]:
    started = time.monotonic()
    result = invoke(
        {
            "prompt": request.prompt,
            "user_id": request.user_id,
            "session_id": request.session_id,
        },
        target=target,
        stream=False,
    )
    return request, result, time.monotonic() - started


def _invoke_session(
    session_number: int,
    total_sessions: int,
    requests: list[TrafficRequest],
    total_requests: int,
    target: Target,
    reporter: ProgressReporter,
) -> list[tuple[TrafficRequest, dict, float]]:
    """Run one session in order so its captured turns remain correlated."""
    first_request = requests[0]
    reporter.log(
        f"Session [{session_number}/{total_sessions}] START | "
        f"user={first_request.user_id} | session={first_request.session_id} | "
        f"{len(requests)} turns"
    )

    outcomes: list[tuple[TrafficRequest, dict, float]] = []
    successes = 0
    for turn_number, request in enumerate(requests, start=1):
        reporter.log(
            f"  [{request.number}/{total_requests}] START | "
            f"session {session_number}/{total_sessions}, turn {turn_number}/{len(requests)}"
        )
        turn_started = time.monotonic()
        try:
            outcome = _invoke(request, target)
        except Exception as error:  # noqa: BLE001 - keep the load run alive
            duration = time.monotonic() - turn_started
            outcome = (
                request,
                {"status": "error", "errors": [f"{type(error).__name__}: {error}"]},
                duration,
            )
        outcomes.append(outcome)

        _, result, duration = outcome
        if result.get("status") == "success":
            successes += 1
            reporter.log(
                f"  [{request.number}/{total_requests}] OK | {duration:.1f}s | "
                f"session {session_number}/{total_sessions}, turn {turn_number}/{len(requests)}"
            )
        else:
            reporter.log(
                f"  [{request.number}/{total_requests}] ERROR | {duration:.1f}s | "
                f"session {session_number}/{total_sessions}, turn {turn_number}/{len(requests)} | "
                f"{result.get('errors', ['unknown error'])}"
            )

    reporter.log(
        f"Session [{session_number}/{total_sessions}] COMPLETE | "
        f"{successes}/{len(requests)} turns succeeded | session={first_request.session_id}"
    )
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate bounded, synthetic agent traffic captured by NAMS.",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Target the deployed AgentCore runtime instead of localhost:7020.",
    )
    parser.add_argument("--users", type=int, default=20, help="Synthetic users (default: 20).")
    parser.add_argument(
        "--sessions-per-user",
        type=int,
        default=3,
        help="Distinct sessions for each synthetic user (default: 3).",
    )
    parser.add_argument(
        "--turns-per-session",
        type=int,
        default=4,
        help="Agent turns in each session (default: 4).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Maximum concurrent invocations (default: 4).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional identifier added to synthetic user and session IDs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request plan without invoking the agent.",
    )
    args = parser.parse_args()

    if min(args.users, args.sessions_per_user, args.turns_per_session, args.concurrency) < 1:
        parser.error("users, sessions-per-user, turns-per-session, and concurrency must be positive")

    run_id = args.run_id or uuid.uuid4().hex[:8]
    target: Target = "deployed" if args.remote else "local"
    requests = build_requests(
        args.users,
        args.sessions_per_user,
        args.turns_per_session,
        run_id,
    )
    print(
        f"Plan: {len(requests)} agent turns | {args.users} users | "
        f"{args.sessions_per_user} sessions/user | {args.turns_per_session} turns/session"
    )
    print(f"Target: {target} | concurrency: {args.concurrency} | run ID: {run_id}")
    print("All profile facts are synthetic. Each completed turn is captured in NAMS.")

    if args.dry_run:
        for request in requests[:5]:
            print(f"[{request.number}] {request.user_id} / {request.session_id}: {request.prompt}")
        if len(requests) > 5:
            print(f"... {len(requests) - 5} more requests")
        return

    successes = 0
    failures = 0
    elapsed: list[float] = []
    started = time.monotonic()
    sessions: dict[str, list[TrafficRequest]] = {}
    for request in requests:
        sessions.setdefault(request.session_id, []).append(request)
    total_sessions = len(sessions)
    reporter = ProgressReporter()

    # Sessions run concurrently, while turns inside each session remain in
    # order and retain a shared client session ID in NAMS metadata.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(
                _invoke_session,
                session_number,
                total_sessions,
                session_requests,
                len(requests),
                target,
                reporter,
            )
            for session_number, session_requests in enumerate(sessions.values(), start=1)
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                outcomes = future.result()
            except Exception as error:  # noqa: BLE001 - keep the load run alive
                failures += 1
                print(f"Session ERROR {error}")
                continue
            for request, result, duration in outcomes:
                elapsed.append(duration)
                if result.get("status") == "success":
                    successes += 1
                else:
                    failures += 1

    total_seconds = time.monotonic() - started
    average = sum(elapsed) / len(elapsed) if elapsed else 0.0
    print(
        f"Complete: {successes} succeeded, {failures} failed, "
        f"{total_seconds:.1f}s total, {average:.1f}s average request time."
    )
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
