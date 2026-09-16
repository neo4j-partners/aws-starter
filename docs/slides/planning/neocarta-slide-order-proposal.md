Start with the problem: agents receive separate pieces of metadata. Show how Neocarta connects those pieces in Neo4j and turns them into context for agents. Each title should state the slide's main idea so readers can follow the story from the titles alone.

Proposed slides, in order:

- **Neocarta: A Semantic Map for Enterprise Data**: Introduce a graph that connects data structure, business meaning, and usage. State that Neocarta is an experimental Neo4j Labs project.
- **Agents See Metadata in Pieces, Not as a Connected Map**: Explain how schemas, business terms, relationships, and query history live in separate systems. Agents need these facts connected to answer business questions.
- **Neocarta Builds a Connected Map of Enterprise Metadata**: Show how Neocarta collects metadata, puts it in a shared format, and links it in Neo4j. Source tables stay in place; selected example values can also be stored in the graph.
- **Neocarta Turns Metadata Into Context for Agents**: Explain how a business question leads to a search of the graph. Neocarta returns relevant data definitions and relationships through its agent tools.
- **Retrieved Context Gives Agents Columns, Values, and Joins**: Show a sample result with table names, column types, example values, and known join keys. Available details depend on what was loaded into the graph.
- **Agents Use Neocarta's Context to Query Source Data**: Follow “Which customers placed the largest orders last quarter?” through one diagram. Neocarta retrieves context, the agent writes the query, and a separate query tool runs it with the configured access controls.
- **Graph Links Connect Business Terms to Tables and Columns**: Trace a saved business term to a column, its table, and related tables. These stored links help the agent identify the data and known joins.
- **Connectors Bring Schemas, Business Terms, and Query History Into One Graph**: Group sources by the context they add, including metric definitions. Keep the full connector list in the appendix.
- **Search Finds Relevant Data, and Graph Links Add Context**: Explain browsing, text search, and search by meaning. Show how search results gain column details, example values, and relationships from the graph.
- **Saved Metric Definitions Tell Agents How to Calculate Results**: Show how agents retrieve a metric's formula and related model details. Define Open Semantic Interchange as a format for sharing business data models.
- **Metadata Updates and Expert Review Keep Context Accurate**: Assign people to review terms, formulas, and links. Refresh the graph as sources change and check queries through the query tool.
- **Future Work: Stored Query Steps Could Help Agents Reuse Earlier Work**: Combine the reuse slides. Propose saving questions, chosen data, queries, feedback, and results so later agents can reuse and check earlier work.
- **One Business Question Provides a Small Starting Point**: Choose one question, load the needed metadata, check the links, and connect an agent and query tool.
- **Measure Answer Quality Before Expanding to More Data**: Check data selection, query correctness, answer quality, response time, and cost. Use the results to choose the next source. Note that the project's evaluation suite is still being built.

Optional appendix slides, in order:

- **Each Connector Adds Specific Metadata From Its Source**: List the schema, glossary, query history, and semantic model connectors. Explain what each supplies.
- **A Shared Graph Model Links Data Structure, Meaning, and Usage**: Combine the detailed model slides. Show tables, columns, example values, business terms, metrics, queries, and their links.
- **The MCP Server Selects Tools Based on Graph Contents and Indexes**: Explain how the server checks the graph and exposes supported tools to agents.
- **Embeddings Let Agents Search Metadata by Meaning**: Explain embeddings as number lists that represent meaning. Create them from graph descriptions after loading metadata.
- **New Connectors Use the Shared Model to Support Existing Agent Tools**: Combine the connector design and contract slides. Explain reading metadata, checking its format, loading the graph, and testing the connector.
