"""Graph tools that query the fleet graph directly with the Neo4j driver.

- :mod:`core.graph.retrieval`: the driver, the retrievers, and the schema cache
- :mod:`core.graph.text2cypher`: Text2Cypher with a query timeout and a row cap
- :mod:`core.graph.neo4j_errors`: classifies driver errors
- :mod:`core.graph.tools`: the Strands tools the specialists use

The Maintenance specialist gets both tools. The Operations specialist gets
only the Cypher tool.
"""

from fleet_supervisor.core.graph.retrieval import close, get_graph_schema
from fleet_supervisor.core.graph.tools import graph_query_tool, vector_search_tool

MAINTENANCE_TOOLS = (graph_query_tool, vector_search_tool)
OPERATIONS_TOOLS = (graph_query_tool,)

__all__ = [
    "MAINTENANCE_TOOLS",
    "OPERATIONS_TOOLS",
    "close",
    "get_graph_schema",
    "graph_query_tool",
    "vector_search_tool",
]
