#!/usr/bin/env bash
# Throw-away smoke test of the Docker stack: own project name, own ports, own volumes; removed at the end.
# Usage (repository root): scripts/docker_smoke.sh   (ports 18443/18080 unless SMOKE_HTTPS_PORT/SMOKE_HTTP_PORT)
set -euo pipefail
cd "$(dirname "$0")/.."
WORK=$(mktemp -d)
trap 'docker compose -p research-smoke --env-file "$WORK/env" -f deploy/docker-compose.yml down -v --remove-orphans >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
KEY=$(docker run --rm python:3.12-slim sh -c "pip -q install cryptography >/dev/null 2>&1 && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")
HTTPS=${SMOKE_HTTPS_PORT:-18443}
cat > "$WORK/env" <<ENV
RESEARCH_SECRETS_KEY=$KEY
DB_PASSWORD=smoke-$(date +%s)
RESEARCH_WEB_ADMIN_EMAIL=admin@example.org
RESEARCH_WEB_ADMIN_PASSWORD=smoke-password-123
RESEARCH_WEB_SIGNUP_DOMAINS=example.org
SITE_ADDRESS=localhost
CADDY_TLS=internal
HTTPS_PORT=$HTTPS
HTTP_PORT=${SMOKE_HTTP_PORT:-18080}
EDGE_SUBNET=${SMOKE_EDGE_SUBNET:-172.31.251.0/24}
ENV
C=(docker compose -p research-smoke --env-file "$WORK/env" -f deploy/docker-compose.yml)
"${C[@]}" config -q
"${C[@]}" up -d --build --wait
curl -fsSk "https://localhost:$HTTPS/api/v1/health" | grep -q '"ok"' && echo "health ok"
curl -fsSk "https://localhost:$HTTPS/login" | grep -qi "<html" && echo "login page ok"
curl -sSk -o /dev/null -w "login POST: %{http_code}\n" -X POST -H 'content-type: application/json' \
  -d '{"email":"admin@example.org","password":"smoke-password-123"}' "https://localhost:$HTTPS/api/v1/auth/login"
"${C[@]}" ps
echo "smoke passed; tearing down"
