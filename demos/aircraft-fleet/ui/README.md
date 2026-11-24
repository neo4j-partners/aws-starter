# Aircraft Fleet Intelligence UI

The browser shows the supervisor's answer, an interactive Neo4j graph, and
the specialist and tool calls for the current question. Select a completed
tool call to highlight its evidence. Start a new chat to clear the graph and
open a new AgentCore conversation.

From `demos/aircraft-fleet/`, start the configured supervisor in one terminal.

```bash
cd supervisor-agent
uv run fleet-supervisor-server
```

In a second terminal, from `demos/aircraft-fleet/`, build and start the UI.
The frontend build uses Node.js 20 or later.

```bash
cd ui
npm ci
npm run build
uv run --project ../supervisor-agent python server.py
```

Open [http://127.0.0.1:8081](http://127.0.0.1:8081) and select **Find
aircraft with hydraulic system issues**. The starter question asks the agent
to include maintenance event IDs so the canvas can show the paths from
aircraft through systems and components to those events.

The UI server logs in to the fleet graph the same way the supervisor's graph
tools do, using the shared fleet `.env`. It reads `NEO4J_PASSWORD_SECRET_ARN`
when that is set, and `NEO4J_USERNAME` and `NEO4J_PASSWORD` otherwise. It
also reads `NEO4J_URI` and `NEO4J_DATABASE`. It uses the login for bounded,
read-only evidence lookups. When Neo4j rejects the login, the server reads the
secret again. If the password has changed, the lookup runs once more with the
new one, and the graph still shows. A password that is still wrong fails the
lookup, and only the graph is lost. Use a read-only fleet login for the UI. The
[Neo4j Visualization Library
license](https://www.npmjs.com/package/@neo4j-nvl/base) covers use with Neo4j
Aura or a commercial Neo4j product.

To use a deployed supervisor, set `AGENT_ARN` and `AWS_REGION` before starting
the UI. Deploy the supervisor version with browser trace support first.
The UI uses the same AWS credential chain and AgentCore invoke permissions as
the [cloud CLI](../supervisor-agent/README.md). `FLEET_SUPERVISOR_URL` overrides
the local invocation URL, and `FLEET_UI_PORT` overrides the UI's port.
