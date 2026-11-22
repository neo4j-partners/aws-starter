"""Aircraft Fleet GraphRAG Agent: a Strands agent that queries Neo4j directly."""

import truststore

# Verify TLS against the operating system's certificate store instead of the CA
# file bundled with this Python, so a newly issued root CA works. This runs
# when the package is first imported, which every console script and the
# Runtime main.py do before they import boto3, urllib3, or neo4j. Those
# libraries bind ssl.SSLContext at import time, so injecting later leaves
# them with the original class and makes boto3 clients fail.
truststore.inject_into_ssl()
