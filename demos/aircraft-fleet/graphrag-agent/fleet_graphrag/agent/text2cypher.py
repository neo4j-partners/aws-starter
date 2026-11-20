"""Text2Cypher retriever with a query timeout and a row cap.

The model writes the Cypher, so one bad query can scan the whole graph or
return millions of rows. :class:`BoundedText2CypherRetriever` runs every
generated query with a server-side transaction timeout and reads at most
``max_rows`` records from the result stream.
"""

from __future__ import annotations

import logging
from typing import Any

import neo4j
from neo4j.exceptions import CypherSyntaxError
from neo4j_graphrag.exceptions import SearchValidationError, Text2CypherRetrievalError
from neo4j_graphrag.generation.prompts import Text2CypherTemplate
from neo4j_graphrag.retrievers import Text2CypherRetriever
from neo4j_graphrag.retrievers.text2cypher import READ_ONLY_QUERY_TYPE, extract_cypher
from neo4j_graphrag.types import RawSearchResult, Text2CypherSearchModel
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class BoundedText2CypherRetriever(Text2CypherRetriever):
    """``Text2CypherRetriever`` that bounds query time and result size.

    ``RawSearchResult.metadata["truncated"]`` is True when the query produced
    more than ``max_rows`` records.
    """

    def __init__(
        self,
        *args: Any,
        timeout_s: float,
        max_rows: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.timeout_s = timeout_s
        self.max_rows = max_rows

    # Copied from neo4j-graphrag 1.24.0
    # neo4j_graphrag/retrievers/text2cypher.py, Text2CypherRetriever.get_search_results.
    # The changes are the two neo4j.Query timeouts and the bounded fetch.
    # tests/test_text2cypher_bounds.py fails if the upstream signature changes.
    def get_search_results(
        self, query_text: str, prompt_params: dict[str, Any] | None = None
    ) -> RawSearchResult:
        try:
            validated_data = Text2CypherSearchModel(query_text=query_text)
        except ValidationError as e:
            raise SearchValidationError(e.errors()) from e

        prompt_template = Text2CypherTemplate(template=self.custom_prompt)

        if prompt_params is not None:
            examples_to_use = prompt_params.pop("examples", None) or (
                "\n".join(self.examples) if self.examples else ""
            )
            schema_to_use = prompt_params.pop("schema", None) or self.neo4j_schema
        else:
            examples_to_use = "\n".join(self.examples) if self.examples else ""
            schema_to_use = self.neo4j_schema
            prompt_params = {}

        prompt = prompt_template.format(
            schema=schema_to_use,
            examples=examples_to_use,
            query_text=validated_data.query_text,
            **prompt_params,
        )
        logger.debug("Text2Cypher prompt: %s", prompt)

        try:
            llm_result = self.llm.invoke(prompt)
            t2c_query = extract_cypher(llm_result.content)
            logger.debug("Text2Cypher query: %s", t2c_query)
            # EXPLAIN plans the query without running it, so a write query is
            # refused before it can touch the database.
            _, explain_summary, _ = self.driver.execute_query(
                query_=neo4j.Query(f"EXPLAIN {t2c_query}", timeout=self.timeout_s),
                database_=self.neo4j_database,
                routing_=neo4j.RoutingControl.READ,
            )
            if explain_summary.query_type != READ_ONLY_QUERY_TYPE:
                raise Text2CypherRetrievalError(
                    "Refusing to execute non-read-only Cypher "
                    f"(query_type={explain_summary.query_type!r}): {t2c_query}"
                )
            # Read one row past the cap to detect truncation. The driver
            # discards the rest of the stream when the transaction closes.
            records = self.driver.execute_query(
                query_=neo4j.Query(t2c_query, timeout=self.timeout_s),
                database_=self.neo4j_database,
                routing_=neo4j.RoutingControl.READ,
                result_transformer_=lambda result: result.fetch(self.max_rows + 1),
            )
        except CypherSyntaxError as e:
            raise Text2CypherRetrievalError(f"Failed to get search result: {e.message}") from e

        truncated = len(records) > self.max_rows
        if truncated:
            logger.info("Text2Cypher result capped at %d rows", self.max_rows)
        return RawSearchResult(
            records=records[: self.max_rows],
            metadata={"cypher": t2c_query, "truncated": truncated},
        )
