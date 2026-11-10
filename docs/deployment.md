# Deployment

The step-by-step install guide is **`docs/deployment-docker.md`** (one LAN Linux machine, Docker Compose);
on Windows, **`docs/deployment-windows.md`** (Docker Desktop with WSL 2, PowerShell scripts).
This page is the short design summary.

## Services (`deploy/docker-compose.yml`)

| Service | What it does | Ports |
|---|---|---|
| `db` | PostgreSQL 16, `dbdata` volume, `pg_isready` health check. | none |
| `migrate` | One-shot `research-web bootstrap`: migrations under a PostgreSQL advisory lock, then the first admin, the sign-up domains and the contact address from `deploy/.env` (only while none is set). Exits. | none |
| `api` | `research-web serve`: the API and the built React app (`RESEARCH_WEB_STATIC_DIR=/app/web`, strict same-origin CSP on pages, `default-src 'none'` on API answers). Health check on `/api/v1/health`. | `8000` inside the network only |
| `worker` | `research-web worker`: claims jobs, runs the pipeline with the requesting user's own keys (decrypted with `RESEARCH_SECRETS_KEY`), writes the `runs` and `cache` volumes. Gets `HTTPS_PROXY`/`NO_PROXY`. `init: true`, `stop_grace_period: 30s` so a stop requeues the running job. | none |
| `proxy` | Caddy 2: TLS (internal CA or your certificate), HSTS, zstd/gzip, 1 MB body limit (31 MB for PDF uploads), HTTP→HTTPS redirect. | the only published ports |

All services share one image built by `deploy/Dockerfile` (Node build of `web/` → Python 3.12 slim, the
hashed dependency lock `deploy/requirements.lock.txt` installed before the source, non-root uid 10001,
`PYTHON_DOTENV_DISABLED=1`, no secrets). Regenerate the lock after changing dependencies:
`uv pip compile pyproject.toml --extra web --extra live --python-version 3.12 --universal --generate-hashes -o deploy/requirements.lock.txt`.

Hardening: `migrate`, `api` and `worker` run with a read-only root file system (writes go to their volumes and
a 256 MB `/tmp`), no Linux capabilities and `no-new-privileges`; `api` and `worker` have memory limits
(`API_MEMORY`, `WORKER_MEMORY`). Caddy and the API share the `edge` network (fixed subnet `EDGE_SUBNET`,
default `172.31.250.0/24`); the API trusts `X-Forwarded-For` only from that subnet, so the per-IP sign-in
limits see the real client address.

## Keys and settings

- `deploy/.env` (from `deploy/.env.example`, git-ignored): `RESEARCH_SECRETS_KEY`, `DB_PASSWORD`, admin
  bootstrap, sign-up domains, contact address, site address/TLS, outbound proxy. **No LLM keys.**
- `deploy/worker.env` (optional, from `deploy/worker.env.example`): organisation-wide search-source keys only.
- `RESEARCH_WEB_DEV_MODE`, `RESEARCH_WEB_ALLOW_DEMO` are forced `false` and the session cookie is `Secure` in
  the compose file; they are not read from `deploy/.env`.
- `RESEARCH_SECRETS_KEY` must be the same for `api` (encrypts) and `worker` (decrypts). Losing it makes saved
  user keys unreadable (users re-enter them); back it up separately from the database dump.

## History

Until 2026-11-03 the stack had a separate nginx `web` image (`deploy/Dockerfile.web`, `deploy/nginx.conf`),
LLM keys in `deploy/worker.env` and a loopback-only port behind an external TLS proxy. That stack stopped
starting once `serve`/`worker` required `RESEARCH_SECRETS_KEY` (per-user keys) and was replaced by the one
above (spec `docs/superpowers/specs/2026-11-03-poc-deploy-design.md`, section 5). The nginx CSP moved into the
API (`research_agent.web.api.errors.FRONTEND_HEADERS`).
