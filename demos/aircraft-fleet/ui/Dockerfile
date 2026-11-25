# syntax=docker/dockerfile:1
#
# The hosted fleet UI: ui/server.py on Lambda behind Lambda Web Adapter.
# The build context is demos/aircraft-fleet/, and its .dockerignore lets in
# only the files below. Build from that folder:
#
#   docker build --platform linux/arm64 -f ui/Dockerfile -t fleet-ui .
#
# Every base image is pinned by version and digest. Each digest was at least a
# week old when it was pinned.

# Build ui/static/bundle.js from the locked esbuild.
FROM docker.io/library/node:22.23.4-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS bundle
WORKDIR /build/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/static/ ./static/
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

# Install the supervisor project's locked runtime dependencies. The project
# itself is not built, so no unlocked build backend is fetched. Its package
# imports from PYTHONPATH instead.
FROM docker.io/library/python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS deps
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12
WORKDIR /app/supervisor-agent
COPY supervisor-agent/pyproject.toml supervisor-agent/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM docker.io/library/python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0@sha256:17cfd08eff1dfea3f6a9a1e9c65fdac80aa4919b6085e746615530f43f57d2f1 /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=deps /app/supervisor-agent/.venv /app/supervisor-agent/.venv
COPY supervisor-agent/fleet_supervisor/ /app/supervisor-agent/fleet_supervisor/
COPY ui/server.py ui/auth.py ui/evidence.py /app/ui/
COPY --from=bundle /build/ui/static/index.html /build/ui/static/style.css /build/ui/static/bundle.js /app/ui/static/
# Lambda's file system is read-only, so compile the app's bytecode now.
RUN python -m compileall -q /app/supervisor-agent/fleet_supervisor /app/ui
ENV PATH=/app/supervisor-agent/.venv/bin:$PATH \
    PYTHONPATH=/app/supervisor-agent \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/ready \
    AWS_LWA_INVOKE_MODE=response_stream
WORKDIR /app/ui
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
