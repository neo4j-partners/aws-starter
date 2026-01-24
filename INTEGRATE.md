# Neo4j Integration Points with AWS Bedrock and AgentCore

## High-Level Summary

- **GraphRAG** - Use Neo4j knowledge graphs to ground Bedrock LLM responses with contextual, connected data that reduces hallucinations by up to 35%
- **Vector Embeddings** - Generate embeddings via Bedrock models and store them in Neo4j's native vector index for hybrid semantic and graph search
- **AWS Glue Connector** - Official Neo4j connector enables serverless ETL from S3, DynamoDB, RDS, Redshift, and Kinesis directly into Neo4j graphs
- **Text-to-Cypher** - Bedrock LLMs translate natural language questions into Cypher queries for direct graph database access
- **Knowledge Graph Creation** - Use Bedrock to extract entities and relationships from unstructured text, then load them into Neo4j
- **Streaming Ingestion** - Connect Neo4j to Kinesis and MSK for real-time data pipelines and change data capture
- **Conversation Memory** - Store chat history in Neo4j using LangChain's Neo4j memory classes for persistent, graph-aware context
- **Bedrock Agents Action Groups** - Create Lambda-based tools that query Neo4j as part of agent workflows
- **SageMaker Pipelines** - Orchestrate data transformation and graph loading as part of ML workflows

---

## GraphRAG: Combining Graphs and Retrieval

Traditional RAG systems use vector similarity to find relevant documents, but they miss the relationships between pieces of information. GraphRAG solves this by combining vector search with graph traversal.

With Neo4j and Bedrock working together, you can:

- Store your enterprise data as a knowledge graph with explicit relationships
- Perform multi-hop reasoning to follow connections between entities
- Combine vector similarity search with graph path traversal in a single query
- Provide the LLM with not just relevant documents, but the context of how those documents relate to each other

Studies by Lettria (an AWS Partner) showed that GraphRAG improves answer correctness from 50% to over 80% compared to vector-only approaches. The graph structure helps the LLM understand context that pure embedding similarity cannot capture.

---

## Vector Embeddings and Hybrid Search

Neo4j includes native vector search capabilities that integrate well with Bedrock's embedding models.

The workflow looks like this:

1. Send text, images, or documents to a Bedrock embedding model (like Titan Embeddings)
2. Store the resulting vectors alongside your graph data in Neo4j
3. Query using a combination of vector similarity and graph relationships

This hybrid approach lets you find semantically similar content while also filtering or enriching results based on graph structure. For example, find documents similar to a query, then traverse the graph to include related entities, authors, or topics.

---

## AWS Glue Connector for ETL

Neo4j has released an official connector for AWS Glue that makes it straightforward to load data from AWS services into your graph.

Supported sources include:

- Amazon S3 (files, data lakes)
- Amazon DynamoDB (NoSQL tables)
- Amazon RDS (relational databases)
- Amazon Redshift (data warehouse)
- Amazon Kinesis Data Streams (real-time data)
- Apache Kafka (via MSK)
- Snowflake and other external systems

The connector translates SQL commands from Glue's visual ETL tool into Cypher statements that create nodes and relationships. You can build serverless data pipelines that continuously update your knowledge graph as source data changes.

This works with both Neo4j AuraDB (the managed cloud service) and self-hosted Neo4j on EC2.

---

## Text-to-Cypher Query Generation

One powerful integration pattern uses Bedrock LLMs to translate natural language questions into Cypher queries.

Instead of building a fixed set of queries, you can:

1. Provide the LLM with your graph schema (node labels, relationship types, property names)
2. Let users ask questions in plain English
3. Have the LLM generate the appropriate Cypher query
4. Execute the query against Neo4j and return results

This enables conversational interfaces over complex graph data. Users can ask questions like "Show me all customers who purchased products in the electronics category and also filed a support ticket last month" without knowing Cypher.

---

## Knowledge Graph Construction from Unstructured Data

Bedrock LLMs can extract structured information from unstructured text, which you can then load into Neo4j.

The process involves:

1. Feed documents (contracts, reports, articles) to a Bedrock model
2. Prompt the model to extract entities (people, organizations, products, concepts)
3. Have the model identify relationships between those entities
4. Generate Cypher statements to create the graph
5. Load the statements into Neo4j using the Python driver or AWS Glue

This turns static documents into a queryable knowledge graph. Over time, you build a connected representation of your enterprise knowledge that agents can traverse.

---

## Real-Time Streaming with Kinesis and MSK

For data that changes frequently, Neo4j integrates with AWS streaming services.

Using the Neo4j Kafka Connector with Amazon MSK:

- Stream events from applications into Kafka topics
- The connector consumes messages and writes them to Neo4j as nodes or relationships
- Changes appear in your graph within seconds

Using Apache Spark Streaming with Kinesis:

- Connect Spark to Kinesis Data Streams
- Transform and enrich the data using Spark
- Write to Neo4j using the Neo4j Spark Connector

These patterns support use cases like fraud detection, recommendation engines, and operational dashboards where you need the graph to reflect current state.

---

## Change Data Capture for Synchronization

If you have an existing relational database and want to keep a Neo4j graph in sync, change data capture (CDC) provides a solution.

The pattern works like this:

1. Enable CDC on your source database (RDS, Aurora, or external)
2. Stream changes to Kafka or Kinesis
3. Transform the changes into graph operations
4. Apply them to Neo4j

This ensures your knowledge graph always reflects the latest state of your operational systems without manual data loads or batch jobs.

---

## Conversation Memory with LangChain

LangChain provides a Neo4j memory class that stores chat history in the graph database.

Benefits of graph-based memory:

- Conversations are stored as connected nodes, not flat records
- You can query across conversations to find patterns
- Relationships between topics, users, and sessions are explicit
- Context retrieval can traverse the conversation graph

This integrates with both standard LangChain and LangGraph agents. While AgentCore provides its own managed memory service, storing memory in Neo4j gives you more control over the structure and additional query capabilities.

---

## Bedrock Agents with Neo4j Action Groups

Although there is no built-in Bedrock Agent integration with Neo4j, you can create custom action groups that query your graph.

The approach:

1. Define an action group in your Bedrock Agent with an OpenAPI schema
2. Implement a Lambda function that connects to Neo4j and runs Cypher queries
3. The agent invokes your action group when it needs graph information

This lets agents answer questions that require relationship traversal, find patterns in connected data, or update the graph based on user interactions.

---

## SageMaker for ML Workflows

Neo4j integrates with SageMaker for machine learning workflows on graph data.

Common patterns include:

- Using SageMaker notebooks to explore and prepare graph data
- Running graph algorithms (community detection, centrality) as part of feature engineering
- Training models on graph-derived features
- Deploying models that query Neo4j for real-time predictions

The Neo4j partners hands-on lab walks through deploying Neo4j alongside SageMaker and building a complete GenAI solution.

---

## AWS Architecture Reference

AWS provides a reference architecture for Knowledge Graphs and GraphRAG with Neo4j that shows how these services work together.

The architecture includes:

- Neo4j AuraDB on AWS for the graph database
- SageMaker for data preparation and model hosting
- Bedrock for LLM access and embedding generation
- LangChain as the orchestration framework
- S3 for document storage
- Glue for ETL pipelines

---

## Use Cases by Industry

**Finance**
- Semantic search across financial documents
- Fraud ring detection through relationship analysis
- Regulatory compliance tracking

**Manufacturing**
- Warranty analytics connecting products, issues, and resolutions
- Supply chain visibility across multi-tier relationships
- Service engineer knowledge retrieval

**Supply Chain**
- Demand sensing using real-time event data
- Supplier relationship mapping
- Risk analysis through multi-hop queries

**Healthcare**
- Patient journey analysis
- Drug interaction networks
- Research literature knowledge graphs

---

## Sources

- [Neo4j AWS Bedrock Integration Press Release](https://neo4j.com/press-releases/neo4j-aws-bedrock-integration/)
- [AWS APN Blog: Neo4j and Amazon Bedrock](https://aws.amazon.com/blogs/apn/leveraging-neo4j-and-amazon-bedrock-for-an-explainable-secure-and-connected-generative-ai-solution/)
- [AWS Architecture: Knowledge Graphs and GraphRAG with Neo4j](https://docs.aws.amazon.com/architecture-diagrams/latest/knowledge-graphs-and-graphrag-with-neo4j/knowledge-graphs-and-graphrag-with-neo4j.html)
- [Neo4j Connector for AWS Glue](https://neo4j.com/blog/developer/neo4j-connector-for-aws-glue/)
- [AWS Database Blog: Change Data Capture from Neo4j](https://aws.amazon.com/blogs/database/change-data-capture-from-neo4j-to-amazon-neptune-using-amazon-managed-streaming-for-apache-kafka/)
- [LangChain Neo4j Chat Message History](https://python.langchain.com/docs/integrations/memory/neo4j_chat_message_history/)
- [Hands-on Lab: Neo4j and Bedrock](https://github.com/neo4j-partners/hands-on-lab-neo4j-and-bedrock)
- [AWS Blog: Building GraphRAG Applications](https://aws.amazon.com/blogs/machine-learning/build-graphrag-applications-using-amazon-bedrock-knowledge-bases/)
- [Amazon Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AWS Blog: AgentCore Memory](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/)
