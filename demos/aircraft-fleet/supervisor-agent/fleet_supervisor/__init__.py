"""Aircraft fleet supervisor agent: a Strands supervisor over two specialist agents."""

import logging
import sys

import truststore

# Verify TLS against the operating system's certificate store instead of the CA
# file bundled with this Python, so a newly issued root CA works on macOS.
#
# inject_into_ssl() replaces ssl.SSLContext. A library that was imported before
# that keeps the original class, and the first boto3 client then fails with
# RecursionError. The console scripts and main.py import this package first,
# but the AgentCore Runtime starts Python under opentelemetry-instrument, which
# imports botocore and urllib3 before main.py runs. In that case the injection
# is skipped, and TLS uses the default CA store. On the Runtime's Linux image
# that is the system store.
_HTTP_MODULES = ("urllib3", "botocore", "requests", "httpx", "neo4j")
_preloaded = sorted(name for name in _HTTP_MODULES if name in sys.modules)
if _preloaded:
    logging.getLogger(__name__).warning(
        "Skipping truststore: %s already imported; using the default CA store.",
        ", ".join(_preloaded),
    )
else:
    truststore.inject_into_ssl()
