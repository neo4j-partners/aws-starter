# Register the AgentCore MCP Gateway in Databricks Unity Catalog

This walks through exposing a deployed `neo4j-agentcore-mcp-server` Gateway to Databricks, so that
AI Playground, Genie Code, and Databricks agents can call the Neo4j MCP tools without ever holding
the Gateway's credentials. Databricks stores the Cognito client credentials in Unity Catalog,
performs the OAuth exchange itself, and refreshes the access token on its own schedule.

Written against the supplier deployment (`./deploy.py --env supplier`), but nothing here is
supplier-specific apart from the names.

## Two objects are required, not one

This is the part that is easy to get wrong.

| Object | Where it appears | What it does |
| --- | --- | --- |
| **HTTP connection** | Catalog Explorer > External Data > Connections | Stores the Gateway URL and the credentials. Public Preview. |
| **MCP Service** | AI Gateway > MCPs, and Catalog Explorer under a schema | Wraps the connection as a governed securable. This is what agents and the Playground actually select. |

If you create only the connection, the Playground's tool picker stays empty no matter how many
privileges you grant. The picker lists MCP Services, and it browses under a schema by default, so a
metastore-level connection is invisible to it twice over. Create both objects.

Reference docs:

- HTTP connections: <https://docs.databricks.com/aws/en/query-federation/http>
- MCP Services: <https://docs.databricks.com/aws/en/agents/mcp-tools/mcp-services>
- Registering one: <https://docs.databricks.com/aws/en/ai-gateway/register-mcp-service>

## Requirements

- Unity Catalog enabled workspace, in a region where Model Serving is supported. External MCP
  servers are gated on Model Serving region availability, including their use from AI Playground.
- `CREATE CONNECTION` on the metastore, or on the schema for a schema-level connection.
- `USE CATALOG`, `USE SCHEMA`, and `CREATE SERVICE` on the target schema, plus `USE CONNECTION` on
  the connection, to create the MCP Service.
- The MCP server must speak Streamable HTTP. The AgentCore Gateway does.

## Step 0. Generate Gateway credentials

```bash
./deploy.py --env supplier credentials   # writes .mcp-credentials.supplier.json
```

Every value Databricks needs is in that file. It is gitignored and holds a live client secret, so
keep it out of commits, shell history, and query history.

## Step 1. Create the HTTP connection, OAuth M2M

The Gateway authenticates with a Cognito client credentials grant, which maps exactly onto the
Databricks OAuth Machine-to-Machine auth type.

| Credentials file field | Connection option | Notes |
| --- | --- | --- |
| `gateway_url` scheme and host | `host` | Origin only, no path. |
| (fixed) | `port` | `443` |
| `gateway_url` path | `base_path` | `/mcp` |
| `client_id` | `client_id` | |
| `client_secret` | `client_secret` | Write-only, never returned by a `get`. |
| `scope` | `oauth_scope` | Space-delimited if there is more than one. |
| `token_url` | `token_endpoint` | |

`access_token` and `token_expires_at` are deliberately unused. See the rationale below.

Build the request body from the credentials file and create the connection through the REST API:

```bash
ENV=supplier                     # matches .mcp-credentials.$ENV.json
CONN=neo4j_agentcore_supplier    # connection name in Unity Catalog
CATALOG=your_catalog
SCHEMA=your_schema
PROFILE=your-databricks-profile

python3 - "$ENV" "$CONN" > /tmp/conn.json <<'PY'
import json, pathlib, sys
from urllib.parse import urlparse

env, name = sys.argv[1], sys.argv[2]
c = json.loads(pathlib.Path(f".mcp-credentials.{env}.json").read_text())
u = urlparse(c["gateway_url"])
print(json.dumps({
    "name": name,
    "connection_type": "HTTP",
    "comment": "Neo4j AgentCore MCP Gateway",
    "options": {
        "host": f"{u.scheme}://{u.hostname}",
        "port": "443",
        "base_path": u.path,
        "client_id": c["client_id"],
        "client_secret": c["client_secret"],
        "oauth_scope": c["scope"],
        "token_endpoint": c["token_url"],
    },
}))
PY

# schema-level, which is what you want
databricks api post \
  "/api/2.1/unity-catalog/connections?parent=schemas/$CATALOG.$SCHEMA" \
  -p "$PROFILE" --json @/tmp/conn.json

# metastore-level alternative, not recommended
# databricks connections create --json @/tmp/conn.json -p "$PROFILE"

rm -f /tmp/conn.json
```

A successful response reports `"credential_type": "OAUTH_M2M"`,
`"securable_kind": "CONNECTION_HTTP_OAUTH_M2M"`, `"provisioning_info": {"state": "ACTIVE"}`, and an
`access_token_expiration` in the options, which is Databricks confirming it already completed the
token exchange against Cognito. The client secret is absent from the response. For a schema-level
connection, `full_name` comes back as `<catalog>.<schema>.<name>` while `name` stays bare.

Create the connection at the **schema** level. The `?parent=schemas/<catalog>.<schema>` query
parameter is the only difference in the payload, and `databricks connections create` without it
lands the connection at the metastore level, which Databricks supports but does not recommend. The
practical consequence is visibility: pickers in AI Playground and Genie Code browse under a schema
by default, so a metastore-level connection is easy to miss. The two namespaces are independent, so
a schema-level connection can carry the same short name as a metastore-level one.

## Step 2. Register the MCP Service

There is no SQL DDL for MCP Services. Use the UI or the REST API.

```bash
CATALOG=your_catalog
SCHEMA=your_schema
SERVICE=neo4j_agentcore_supplier

databricks api post \
  "/api/2.1/unity-catalog/mcp-services?parent=schemas/$CATALOG.$SCHEMA&mcp_service_id=$SERVICE" \
  -p "$PROFILE" \
  --json "{
    \"comment\": \"Neo4j AgentCore MCP server\",
    \"config\": {
      \"source_connection\": { \"name\": \"connections/$CATALOG.$SCHEMA.$CONN\" },
      \"include_tool_selectors\": []
    }
  }"
```

Notes on the payload:

- `source_connection.name` is `connections/<name>` for a metastore-level connection, and
  `connections/<catalog>.<schema>.<name>` for a schema-level one.
- `include_tool_selectors: []` exposes every tool the server advertises. To narrow it, use prefix
  or exact-match patterns, for example `["get_*"]`. Exclusion patterns such as `!delete_*` are not
  supported. Restricting to the read tools is a reasonable hardening step, since the Neo4j MCP
  server exposes `get_neo4j_schema` and `read_neo4j_cypher` only.
- The service name is immutable after creation, but the connection it points at is not. To repoint
  an existing service, `PATCH` with `update_mask=config` and send the whole `config` object.
  A narrower `update_mask=config.source_connection` is rejected with
  `Unsupported update_mask path`.

  ```bash
  databricks api patch \
    "/api/2.1/unity-catalog/mcp-services/$CATALOG.$SCHEMA.$SERVICE?update_mask=config" \
    -p "$PROFILE" \
    --json "{
      \"config\": {
        \"source_connection\": { \"name\": \"connections/$CATALOG.$SCHEMA.$CONN\" },
        \"include_tool_selectors\": []
      }
    }"
  ```

  Because `update_mask=config` replaces the object, resend `include_tool_selectors` or you will
  silently widen a narrowed service back to all tools.

The response echoes `"securable_type": "MCP_SERVICE"` and a `name` of
`mcp-services/<catalog>.<schema>.<service>`.

Equivalent UI path: **AI Gateway > MCPs > Register MCP Server**, or **Catalog > (schema) > Create >
MCP Service**. In that dialog, turn off **Browse under a schema** to pick a metastore-level
connection.

## Step 3. Verify from the command line

Two endpoints are worth checking, because they fail for different reasons.

The connection proxy, which proves the stored credentials reach the Gateway:

```bash
DTOK=$(databricks auth token -p "$PROFILE" | jq -r .access_token)

curl -s -X POST \
  "https://<workspace-host>/api/2.0/unity-catalog/connections/$CATALOG.$SCHEMA.$CONN/proxy" \
  -H "Authorization: Bearer $DTOK" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

The AI Gateway endpoint, which proves the MCP Service and its grants are right:

```bash
curl -s -X POST \
  "https://<workspace-host>/ai-gateway/mcp-services/$CATALOG.$SCHEMA.$SERVICE" \
  -H "Authorization: Bearer $DTOK" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Both should list the Gateway's tools. Names carry the Gateway target prefix, so they come back as
`neo4j-mcp-server-target___get_neo4j_schema` and `neo4j-mcp-server-target___read_neo4j_cypher`
rather than the bare tool names. Anything that pattern-matches on tool names, including
`include_tool_selectors`, has to account for that prefix.

No `Authorization` header from your request survives the hop. The proxy strips Databricks headers
before forwarding, and injects the connection's credentials instead.

## Step 4. Test in AI Playground

1. Open AI Playground and select a model labeled **Tools enabled**.
2. **Tools > + Add tool > MCP Servers**.
3. Choose **External MCP servers**, then select `<catalog>.<schema>.<service>`.
4. Start with "get the Neo4j schema", which is the cheapest proof the tool call round-trips.
5. Then ask something structural, for example "find every Customer that owns another Customer
   through an OWNED_BY chain of two or more hops", to confirm the model writes Cypher and the
   Gateway executes it.

Genie Code works the same way: Genie Code pane > **Settings** > **MCP Servers** > **Add Server** >
**External MCP server**, then pick the connection. Note that this picker selects the *connection*,
not the MCP Service, which is another reason to keep the connection schema-level.

### Where it will not appear

The Databricks One page at `/one/tools/connections` (**Customizations > Connections**) does not list
a connection like this one, and no amount of granting changes that. Every tile on that page is a
Databricks-provided connector whose connection has `credential_type: OAUTH_U2M_MAPPING`, meaning
Databricks-managed per-user OAuth, backed by a `system.ai.*` MCP Service. That page exists so each
user can sign into their own Gmail, GitHub, or Slack account. A shared-principal connection, whether
bearer token or OAuth M2M, has no per-user login step, so it renders no toggle.

Chasing that page is a dead end for an AgentCore Gateway fronted by a Cognito client credentials
client, because there is no authorization-code flow or DCR endpoint for Databricks to drive. To
reach a chat surface in Databricks One, deploy an agent that uses the MCP Service and use the agent
under **Agents**.

## Grants

Grant `EXECUTE` on the **MCP Service**. One grant covers all of its tools.

```bash
databricks api patch \
  "/api/2.1/unity-catalog/permissions/mcp_service/$CATALOG.$SCHEMA.$SERVICE" \
  -p "$PROFILE" \
  --json '{"changes": [{"principal": "your-group", "add": ["EXECUTE"]}]}'
```

Do not grant `USE CONNECTION` to end users. It lets them call the Gateway directly through the
connection proxy, or register their own MCP Service over the same connection, which bypasses your
tool selection, service policies, and audit trail. Keep connection access to the people who
administer the deployment.

## Rotation and teardown

The connection holds a copy of the Cognito client secret, so it goes stale if the stack is
redeployed with new credentials, and the `host` goes stale if the Gateway URL changes. After any
`./deploy.py --env <name> deploy` that recreates the Gateway or the Cognito client, regenerate
credentials and update the connection options rather than recreating it, so the MCP Service keeps
pointing at the same object.

```bash
# untested shapes, confirm against your CLI version before relying on them
databricks connections update "$CONN" --json @/tmp/conn-options.json -p "$PROFILE"
databricks api delete "/api/2.1/unity-catalog/mcp-services/$CATALOG.$SCHEMA.$SERVICE" -p "$PROFILE"
databricks connections delete "$CONN" -p "$PROFILE"
```

Delete the MCP Service before the connection. The service references the connection, and a deleted
connection surfaces as `is_deleted` on the service rather than cleaning itself up.

## What was done differently for the supplier deployment

Four deliberate departures from the shortest path in the docs.

**OAuth M2M rather than the bearer token.** The docs lead with a bearer token and
`.mcp-credentials.*.json` hands you a ready-made `access_token`, which is tempting. That token is a
Cognito access token with a lifetime measured in hours, so the connection would have broken by the
next morning and needed a manual re-paste on every demo day. Feeding Databricks the `client_id`,
`client_secret`, `oauth_scope`, and `token_endpoint` instead makes Databricks the token holder, and
it mints and refreshes on its own. The stored credential now outlives the stack rather than the
day.

**The REST API rather than `CREATE CONNECTION ... TYPE HTTP`.** The SQL form is the documented happy
path, but running it writes the client secret in plaintext into query history, where anyone with
access to `system.query.history` can read it later. The docs' own mitigation is
`bearer_token secret('scope','key')`, which means standing up a secret scope first. Going through
`databricks connections create --json @file` keeps the secret out of query history entirely with no
extra Databricks objects, and the temp file is deleted immediately after. If you do use SQL, use
the secret form.

**Two connections exist for one Gateway.** The first attempt created the connection at the metastore
level, which is the default for `databricks connections create` and the reason it never appeared in
the schema-scoped pickers. Rather than migrate it, a second, schema-level connection with the same
short name was created in the demo schema and the MCP Service was repointed at it with the `PATCH`
above. Both are live and both proxy successfully, so the metastore-level one is now redundant and
safe to delete once nothing references it. On a fresh setup, create only the schema-level one.

**A catalog name containing a hyphen.** The demo's catalog is hyphenated. Both the REST create call
and the `/ai-gateway/mcp-services/...` invocation path handled it without quoting. If a UI path
chokes on it, register the service under a hyphen-free schema instead. SQL references to that
catalog still need backticks, as always.

## Local MCP clients, for contrast

Registering the Gateway in Unity Catalog is independent of pointing a local client at it. Claude
Code, Claude Desktop, and Cursor can either:

- talk to the AgentCore Gateway directly, with the Cognito `access_token` from
  `.mcp-credentials.*.json` in an `Authorization: Bearer` header, which is what `cloud-http.sh` and
  `docs/CLAUDE_DESKTOP.md` describe, and which needs a re-paste whenever that token expires, or
- go through Databricks, pointing at
  `https://<workspace-host>/api/2.0/unity-catalog/connections/<conn>/proxy` or the
  `/ai-gateway/mcp-services/<full-name>` endpoint with a Databricks token, which trades Cognito
  token upkeep for Databricks token upkeep and gains the audit trail.

Neither is better in the abstract. Direct is fewer moving parts for local development, the
Databricks path is the one to use when the calls should be governed and logged alongside everything
else in the workspace.
