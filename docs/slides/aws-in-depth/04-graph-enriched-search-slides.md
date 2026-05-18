---
marp: true
theme: default
paginate: true
---

<style>
section {
  --marp-auto-scaling-code: false;
}

li {
  opacity: 1 !important;
  animation: none !important;
  visibility: visible !important;
}

/* Disable all fragment animations */
.marp-fragment {
  opacity: 1 !important;
  visibility: visible !important;
}

ul > li,
ol > li {
  opacity: 1 !important;
}
</style>

# Graph-Enriched Search with GraphRAG

Retrievers, decision frameworks, and going beyond plain vector search

---

## Powered by the Neo4j Python GraphRAG Library

Everything in this deck is built on the **Neo4j Python GraphRAG Library**.

- **Retrievers**: ready-made Vector, Vector Cypher, and Text2Cypher search patterns
- **Embeddings**: pluggable embedders (Amazon Bedrock Titan, OpenAI, and more)
- **GraphRAG pipeline**: one call to retrieve context and generate a grounded answer

---

## From Knowledge Graph to Answers

You have a knowledge graph with:

- **Entities**: Aircraft, systems, components, maintenance events, sensors
- **Relationships**: HAS_SYSTEM, HAS_COMPONENT, HAS_EVENT, HAS_SENSOR, DESCRIBES
- **Embeddings**: Vector representations for semantic search

**The question**: How do you *retrieve* the right information to answer user questions?

---

## What is a Retriever?

A **retriever** searches your knowledge graph and returns relevant information.

**Three retrieval patterns:**

| Retriever | What It Does |
|-----------|--------------|
| **Vector** | Semantic similarity search across text chunks |
| **Vector Cypher** | Semantic search + graph traversal for relationships |
| **Text2Cypher** | Natural language to Cypher query for precise facts |

Each pattern excels at different question types.

---

## The GraphRAG Class

Retrievers work with the **GraphRAG** class, which combines retrieval with LLM generation:

```
User Question
    ↓
Retriever finds relevant context
    ↓
Context passed to LLM
    ↓
LLM generates grounded answer
```

The retriever's job is finding the right context. The LLM's job is generating a coherent answer from that context.

---

## GraphRAG: Graph-Enriched Retrieval

- **The graph holds** structured connections and domain knowledge: chunked, embedded, entity-extracted documents plus operational data
- **Search finds the starting points:** chunks closest in meaning to the question
- **Graph traversal enriches:** follows entities and relationships from those chunks
- **Agents receive richer context** than text search alone

Vector or fulltext search finds relevant chunks (standard RAG). What GraphRAG adds is graph traversal from those chunks through the entities and relationships surrounding them.

---

![bg contain](images/graphrag-retrieval-flow.png)

---

## Choosing the Right Retriever

| Question Pattern | Best Retriever |
|-----------------|----------------|
| "What is...", "Tell me about..." | Vector |
| "Which [entities] are affected by..." | Vector Cypher |
| "How many...", "List all..." | Text2Cypher |
| Content about topics | Vector |
| Content + relationships | Vector Cypher |
| Facts, counts, aggregations | Text2Cypher |

---

## The Decision Framework

**Ask yourself:**

1. **Am I looking for content or facts?**
   - Content: Vector or Vector Cypher
   - Facts: Text2Cypher

2. **Do I need related entities?**
   - No: Vector
   - Yes: Vector Cypher

3. **Is this about relationships?**
   - Traversals: Vector Cypher or Text2Cypher
   - Semantic: Vector

---

# Vector Retriever

---

## What is a Vector Retriever?

The **simplest retriever**, finds content by meaning, not keywords.

**How it works:**

1. Convert your question to an embedding
2. Search vector index for similar chunk embeddings
3. Return the most semantically similar chunks

**Key insight:** "Engine problems" finds content about "bearing wear" and "vibration exceedance" even without exact word matches.

---

## Creating a Vector Retriever

```python
from neo4j_graphrag.retrievers import VectorRetriever

vector_retriever = VectorRetriever(
    driver=driver,                    # Neo4j connection
    index_name='chunkEmbeddings',     # Vector index name
    embedder=embedder,                # Embedding model
    return_properties=['text']        # Properties to return
)
```

**Components:**

- **Driver**: Connection to Neo4j
- **Index**: Where embeddings are stored
- **Embedder**: Model that creates embeddings (e.g., OpenAI)

---

## Performing a Search

```python
query = "What maintenance issues affect the turbine on aircraft AC1001?"

results = vector_retriever.search(
    query_text=query,
    top_k=5  # Return 5 most similar chunks
)

for record in results.records:
    print(f"Score: {record['score']:.4f}")
    print(f"Text: {record['text'][:200]}...")
```

**Each result includes:**

- **text**: The chunk content
- **score**: Similarity score (0-1, higher = more similar)

---

## Understanding Similarity Scores

| Score Range | Interpretation |
|-------------|----------------|
| 0.95-1.0 | Extremely similar (near-exact match) |
| 0.90-0.95 | Highly relevant |
| 0.85-0.90 | Relevant |
| 0.80-0.85 | Moderately relevant |
| < 0.80 | Weak relevance |

Higher scores indicate stronger semantic matches.

---

## Vector Retriever: Best For and Limits

**Use Vector Retriever when:**

- Finding conceptually similar content
- Questions like "What is...", "Tell me about...", "Explain..."
- Exploratory questions about topics

**Limitations (returns text only):**

- No entity relationships, no structured data
- Can't aggregate across entities or traverse connections
- "What maintenance affects the turbine on AC1001?" returns maintenance chunks that may not be AC1001-specific

**When you need more:** Use Vector Cypher Retriever.

---

# Vector Cypher Retriever

---

## Beyond Basic Vector Search

**Vector Retriever:** Returns text chunks only.

**Vector Cypher Retriever:** Returns text chunks + related entities from graph traversal.

```
Query: "What maintenance affects components?"
    ↓
Vector Search: Find relevant chunks
    ↓
Graph Traversal: From chunks → Components → MaintenanceEvents
    ↓
Result: Content + structured entity data
```

---

## How It Works

**Two-step process:**

1. **Vector Search** (semantic)
   - Find chunks similar to your question
   - Same as Vector Retriever

2. **Cypher Traversal** (structural)
   - From each chunk, traverse the graph
   - Gather related entities and relationships
   - Return enriched context

**The combination:** Semantic relevance + graph intelligence.

---

## Creating a Vector Cypher Retriever

```python
from neo4j_graphrag.retrievers import VectorCypherRetriever

retrieval_query = """
MATCH (node)-[:FROM_DOCUMENT]-(doc:Document)-[:DESCRIBES]-(component:Component)
OPTIONAL MATCH (component)-[:HAS_EVENT]->(event:MaintenanceEvent)
WITH node, score, component, collect(event.description)[0..20] AS events
RETURN node.text AS text, score,
       {component: component.name, events: events} AS metadata
ORDER BY score DESC
"""

retriever = VectorCypherRetriever(
    driver=driver,
    index_name='chunkEmbeddings',
    embedder=embedder,
    retrieval_query=retrieval_query
)
```

---

## Understanding the Retrieval Query

**The library provides automatically:**

```cypher
CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
YIELD node, score
-- Your query starts here with node and score --
```

**Your retrieval_query:**

- Receives `node` (matched chunk) and `score` (similarity)
- Traverses from node to related entities
- Returns enriched results

---

## Query Breakdown

```cypher
-- Traverse from chunk to component
MATCH (node)-[:FROM_DOCUMENT]-(doc:Document)-[:DESCRIBES]-(component:Component)

-- Get related events (OPTIONAL so components without events still appear)
OPTIONAL MATCH (component)-[:HAS_EVENT]->(event:MaintenanceEvent)

-- Aggregate events, limit to 20
WITH node, score, component, collect(event.description)[0..20] AS events

-- Return chunk text + metadata
RETURN node.text AS text, score,
       {component: component.name, events: events} AS metadata
```

---

## Why OPTIONAL MATCH Matters

**Without OPTIONAL MATCH:**

```cypher
MATCH (component)-[:HAS_EVENT]->(event)
```

Only returns components that *have* maintenance events.

**With OPTIONAL MATCH:**

```cypher
OPTIONAL MATCH (component)-[:HAS_EVENT]->(event)
```

Returns *all* components; events list is empty if none exist.

**Use OPTIONAL MATCH** for complete results.

---

## The Chunk as Anchor

**Critical concept:** You can only traverse from what vector search finds.

**Example problem:**

- Query: "What maintenance affects the turbine on AC1001?"
- Vector search finds: Chunks about "turbine maintenance" (not AC1001-specific)
- Traversal: Goes to components mentioned in those chunks
- Result: May miss AC1001 if chunks are generic!

**Solution:** Ensure your question surfaces relevant chunks, or use Text2Cypher for entity-specific queries.

---

## Vector Cypher: Best For

**Use Vector Cypher Retriever when:**

- You need content AND related entities
- Questions involve relationships
- You want to traverse from relevant content to connected data

**Example questions:**

- "Which components are affected by high vibration readings?"
- "What sensors do systems mention alongside the turbine?"
- "What maintenance events connect to components on the engine system?"

---

# Text2Cypher Retriever

---

## From Natural Language to Database Queries

**The problem:** Some questions need precise facts, not semantic search.

**Text2Cypher solution:**

1. User asks in natural language
2. LLM generates Cypher from the question
3. Query runs; structured results returned

**Example:**

- Q: "How many maintenance events affect aircraft AC1001?"
- Generated: `MATCH (a:Aircraft {tail:'AC1001'})-[:HAS_SYSTEM]->(:System)-[:HAS_COMPONENT]->(:Component)-[:HAS_EVENT]->(e) RETURN count(e)`
- Result: `12`

---

## How It Works

```
User: "Which components are on aircraft AC1001?"
    ↓
[LLM + Schema] → Generate Cypher
    ↓
MATCH (a:Aircraft {tail: 'AC1001'})-[:HAS_SYSTEM]->(:System)
      -[:HAS_COMPONENT]->(c:Component)
RETURN c.name
    ↓
[Execute Query]
    ↓
Result: High-pressure Turbine, Compressor, Fuel Pump, ...
```

---

## Creating a Text2Cypher Retriever

```python
from neo4j_graphrag.retrievers import Text2CypherRetriever
from neo4j_graphrag.schema import get_schema

# Schema tells LLM what's queryable
schema = get_schema(driver)

text2cypher_retriever = Text2CypherRetriever(
    driver=driver,
    llm=llm,                    # LLM for Cypher generation
    neo4j_schema=schema         # Graph structure
)
```

**The schema is critical:** Without it, the LLM guesses (often incorrectly).

---

## The Role of Schema

**Schema tells the LLM:**

```
Node properties:
  Aircraft {tail: STRING, model: STRING, operator: STRING}
  System {name: STRING, type: STRING}
  Component {name: STRING, type: STRING}
  Sensor {name: STRING, metric: STRING}
  MaintenanceEvent {description: STRING, severity: STRING}

Relationships:
  (:Aircraft)-[:HAS_SYSTEM]->(:System)
  (:Component)-[:HAS_EVENT]->(:MaintenanceEvent)
```

**With schema:** LLM knows exactly what entities and relationships exist.
**Without schema:** LLM invents non-existent properties and relationships.

---

## Text2Cypher: Best For

**Use Text2Cypher when:**

- You need precise facts, counts, or lists
- Question is about specific entities
- Aggregations are needed
- Direct graph queries (no semantic search)

**Example questions:**

- "How many maintenance events occurred on AC1001?"
- "List all components on aircraft AC1001"
- "Which aircraft has the most maintenance events?"
- "What is the average number of events per component?"

---

## Limitations

**Text2Cypher requires questions that map to schema:**

- Question: "Which component is most likely to fail next quarter?"
- Problem: No predictive property in schema
- Result: Cannot generate valid query

**Text2Cypher may struggle with:**

- Ambiguous questions
- Questions requiring interpretation
- Content that lives in text chunks (use Vector instead)

---

## Security Considerations

Text2Cypher executes LLM-generated queries. Important safeguards:

- **Use read-only credentials**: Prevent accidental data modification
- **Validate queries**: Check for dangerous operations (DELETE, DROP)
- **Limit results**: Ensure LIMIT clauses prevent unbounded returns
- **Monitor usage**: Log generated queries for review
- **Trust boundaries**: Don't expose to untrusted users

---

## Comparing All Three Retrievers

| Question | Best Retriever | Why |
|----------|---------------|-----|
| "What is exhaust gas temperature?" | Vector | Semantic content |
| "Which aircraft have components with critical events?" | Vector Cypher | Content + entities |
| "How many maintenance events on AC1001?" | Text2Cypher | Precise count |
| "Tell me about the CFM56 engine" | Vector | Exploratory content |
| "List AC1001 components" | Text2Cypher | Specific entity facts |

---

## Each Retriever Becomes an Agent Tool

In the fleet-agent sample, each retriever becomes one single-responsibility tool. Its docstring is the routing logic the LLM reads.

```python
@tool
def vector_search_tool(query: str, top_k: int = 5) -> str:
    """Semantic search over document chunks. Conceptual questions."""
    return _vector_retriever().search(query_text=query, top_k=top_k)

@tool
def related_entities_tool(query: str, top_k: int = 5) -> str:
    """Search, then traverse to connected components and events."""
    return _vector_cypher_retriever().search(query_text=query, top_k=top_k)

@tool
def graph_query_tool(question: str) -> str:
    """Generate and run read-only Cypher. Counts, lists, exact facts."""
    return _text2cypher_retriever().search(query_text=question)
```

One tool per retriever; routing is driven by the model.

---

## Summary

Graph-enriched search gives you three retrieval patterns:

- **Vector Retriever**: Semantic search across chunks. Best for content and topic exploration. No graph relationships.
- **Vector Cypher Retriever**: Vector search then graph traversal, anchored on the chunk. Best for content AND relationships.
- **Text2Cypher Retriever**: Schema-guided Cypher from natural language. Best for facts, counts, and specific entities.

**Key takeaway:** Vector search finds the starting points; graph traversal enriches them. Match the retriever to the question.
