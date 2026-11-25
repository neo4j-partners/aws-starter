"""Ask the supervisor one question, or serve the browser UI.

    uv run fleet-client ask "Which components fail most often?"
    uv run fleet-client ask --cloud "Which routes have the most delays?"
    uv run fleet-client ui
    uv run fleet-client ui --cloud

Both commands use the local supervisor unless ``--cloud`` is given, even when
the shared .env sets ``AGENT_ARN``. With ``--cloud`` they use the deployed
runtime that ``AGENT_ARN`` names. Both read the shared aircraft-fleet .env, or
the file ``FLEET_ENV_FILE`` names.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from fleet_supervisor.client import cli
from fleet_supervisor.client.fleet_env import load_fleet_env, require_agent_arn

UI_SERVER = Path(__file__).resolve().parents[3] / "ui" / "server.py"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fleet-client",
        description="Run the fleet CLI or the browser UI against the local or deployed supervisor.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask", help="ask the supervisor one question")
    ask.add_argument("prompt", nargs="*", help="the question to ask")
    ask.add_argument("--session-id", help="reuse a session ID across calls")
    ui = commands.add_parser("ui", help="serve the browser UI")
    for command in (ask, ui):
        command.add_argument(
            "--cloud", action="store_true", help="use the deployed runtime that AGENT_ARN names"
        )
    return parser


def serve_ui(cloud: bool) -> None:
    """Replace this process with ``ui/server.py``, set to relay the chosen supervisor."""
    mode = "cloud" if cloud else "local"
    os.environ["FLEET_SUPERVISOR_MODE"] = mode
    print(f"Serving the UI against the {mode} supervisor.", flush=True)
    # Running the file puts ui/ first on sys.path, so its own imports resolve.
    os.execv(sys.executable, [sys.executable, str(UI_SERVER)])


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    load_fleet_env()
    if args.cloud:
        require_agent_arn()
    if args.command == "ask":
        cli.ask(" ".join(args.prompt) or cli.DEFAULT_PROMPT, args.session_id, cloud=args.cloud)
    else:
        serve_ui(cloud=args.cloud)
