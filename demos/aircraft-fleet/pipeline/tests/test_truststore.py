"""The truststore injection in populate_aircraft_db/__init__.py must never break boto3.

Each case runs in a fresh Python process, because the injection happens once
per process at package import.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]

# Creating a client resolves credentials and endpoints but makes no AWS call.
MAKE_CLIENT = "import boto3; boto3.client('sts', region_name='us-east-1')"


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_package_first_injects_truststore() -> None:
    code = (
        "import populate_aircraft_db, ssl, truststore; "
        "assert ssl.SSLContext is truststore.SSLContext; " + MAKE_CLIENT
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert "Skipping truststore" not in result.stderr


def test_preloaded_http_stack_skips_injection() -> None:
    code = (
        "import urllib3, botocore, ssl, truststore; import populate_aircraft_db; "
        "assert ssl.SSLContext is not truststore.SSLContext; " + MAKE_CLIENT
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert "Skipping truststore" in result.stderr
