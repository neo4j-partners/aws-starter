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
cd ../supervisor-agent
uv run fleet-client ui
```

From `ui/`, `uv run --project ../supervisor-agent python server.py` also starts
the UI against the local supervisor.

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

To use the deployed supervisor, run `uv run fleet-client ui --cloud` from
`supervisor-agent/`. It reads `AGENT_ARN` and `AWS_REGION` from the shell or
the shared `.env`. Without `AGENT_ARN`, it stops and says to run
`./agent.sh deploy`. Deploy the supervisor version with browser trace support
first. The UI uses the same AWS credential chain and AgentCore invoke
permissions as the [cloud CLI](../supervisor-agent/README.md).

The UI picks its supervisor from `FLEET_SUPERVISOR_MODE`, which is `local` or
`cloud`. `fleet-client ui` sets it from the `--cloud` flag. When the setting is
unset, the UI uses the local supervisor, even when `AGENT_ARN` is set. In cloud
mode, a missing `AGENT_ARN` stops the UI at startup. `FLEET_ENV_FILE` names a
different `.env`. `FLEET_SUPERVISOR_URL` overrides the local invocation URL,
and `FLEET_UI_PORT` overrides the UI's port.

## Login

`FLEET_UI_AUTH` sets the login, and it is `none` or `cognito`. When it is
unset, the UI has no login, so local runs work as before. Any other value
stops the UI at startup.

With `cognito`, every route needs a Cognito session. The two exceptions are
the login routes under `/auth/` and `GET /ready`. The page redirects to the
login, and every other route returns 401 with no supervisor or Neo4j call.
When a question gets a 401, the browser goes to the login again. The login
uses the authorization code flow with PKCE and asks only for the `openid`
scope. The app client is public and has no secret. The UI verifies the ID
token's signature against the pool's keys. It also checks the issuer,
audience, expiry, and token use, and it keeps the token in an HttpOnly,
Secure, SameSite=Lax cookie. The UI uses no refresh tokens, so an expired
session logs in again. `/auth/logout` clears the cookie and ends the Cognito
session.

Cognito mode needs these settings. A missing one stops the UI at startup.

| Setting | Value |
|---------|-------|
| `COGNITO_USER_POOL_ID` | The user pool ID. |
| `COGNITO_CLIENT_ID_PARAMETER` | The SSM String parameter that holds the app client ID. The UI reads it once at startup. |
| `COGNITO_DOMAIN` | The managed login base URL, starting with `https://`. |
| `AWS_REGION` | The pool's region. Lambda sets it to the function's region. |

The app client allows `https://{host}/auth/callback` as its callback URL and
`https://{host}/` as its sign-out URL. The host comes from the request.

A signed-in question sends the user's Cognito `sub` to the supervisor as its
memory user. The supervisor session ID is a SHA-256 hash of the user and the
browser's session ID. A user who sends another user's session ID still gets a
separate conversation. Local runs send no user and the browser's session ID as
before.

## Container image

`Dockerfile` builds the hosted UI as an arm64 image for Lambda with [Lambda
Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) in response
streaming mode. Build it from `demos/aircraft-fleet/`, which is the build
context.

```bash
docker build --platform linux/arm64 -f ui/Dockerfile -t fleet-ui .
docker run --rm -p 127.0.0.1:8080:8080 -e FLEET_UI_AUTH=none fleet-ui
curl http://127.0.0.1:8080/ready
```

The image builds `static/bundle.js` from the locked esbuild. It installs the
supervisor project's locked dependencies, without dev dependencies, and listens
on port 8080. Each base image is pinned by version and digest. The
`.dockerignore` in `demos/aircraft-fleet/` lets in only the files the image
needs. It always leaves out `.env` files, `.mcp-credentials*.json`, and the
AgentCore CLI state.
