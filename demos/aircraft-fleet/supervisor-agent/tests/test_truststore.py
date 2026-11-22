"""The truststore injection in fleet_supervisor/__init__.py must never break boto3.

Each case runs in a fresh Python process, because the injection happens once
per process at package import.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]

# Creating a client resolves credentials and endpoints but makes no AWS call.
MAKE_CLIENT = "import boto3; boto3.client('sts', region_name='us-east-1')"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ | {
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "OTEL_TRACES_EXPORTER": "none",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_LOGS_EXPORTER": "none",
    }
    return subprocess.run(
        args, cwd=PROJECT_DIR, env=env, capture_output=True, text=True, timeout=120
    )


def test_package_first_injects_truststore() -> None:
    code = (
        "import fleet_supervisor, ssl, truststore; "
        "assert ssl.SSLContext is truststore.SSLContext; " + MAKE_CLIENT
    )
    result = _run([sys.executable, "-c", code])
    assert result.returncode == 0, result.stderr
    assert "Skipping truststore" not in result.stderr


def test_preloaded_http_stack_skips_injection() -> None:
    code = (
        "import urllib3, botocore, ssl, truststore; import fleet_supervisor; "
        "assert ssl.SSLContext is not truststore.SSLContext; " + MAKE_CLIENT
    )
    result = _run([sys.executable, "-c", code])
    assert result.returncode == 0, result.stderr
    assert "Skipping truststore" in result.stderr


def test_runtime_start_under_opentelemetry_instrument() -> None:
    """The AgentCore Runtime starts the agent under opentelemetry-instrument."""
    instrument = shutil.which("opentelemetry-instrument", path=str(Path(sys.executable).parent))
    if instrument is None:
        pytest.skip("opentelemetry-instrument is not installed")
    code = "import fleet_supervisor.server; " + MAKE_CLIENT
    result = _run([instrument, sys.executable, "-c", code])
    assert result.returncode == 0, result.stderr
    assert "RecursionError" not in result.stderr
