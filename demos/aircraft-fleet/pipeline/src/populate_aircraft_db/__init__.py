"""Load the Aircraft Digital Twin dataset into Neo4j."""

import logging
import sys

import truststore

# Verify TLS against the operating system's certificate store instead of the CA
# file bundled with this Python, so a newly issued root CA works.
#
# inject_into_ssl() replaces ssl.SSLContext. A library that was imported before
# that keeps the original class, and the first boto3 client then fails with
# RecursionError. Every console script imports this package before boto3,
# urllib3, or neo4j. A launcher that imports them first, such as
# opentelemetry-instrument, would hit that error, so the injection is skipped
# then, and TLS uses the default CA store. The fleet agents use the same check.
_HTTP_MODULES = ("urllib3", "botocore", "requests", "httpx", "neo4j")
_preloaded = sorted(name for name in _HTTP_MODULES if name in sys.modules)
if _preloaded:
    logging.getLogger(__name__).warning(
        "Skipping truststore: %s already imported; using the default CA store.",
        ", ".join(_preloaded),
    )
else:
    truststore.inject_into_ssl()
