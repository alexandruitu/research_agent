# Deployment

The web app runs as four Docker Compose services defined in `deploy/docker-compose.yml`.
All commands below are run from the repository root.

## 1. What runs where

| Service | What it does | Holds provider keys |
|---|---|---|
| `db` | PostgreSQL 16; data in the `dbdata` volume. Not published to the host. | no |
| `migrate` | Runs `research-web migrate` once, after `db` is healthy, then exits. | no |
| `api` | `research-web serve` on port 8000, published on `127.0.0.1:8000` only. Mounts the run, eval and gold folders read-only. Never runs the pipeline. | no |
| `worker` | `research-web worker`: claims jobs from the database, runs the research pipeline in a child process, writes run folders to the `runs` volume, imports finished runs. | **yes, only this one** |

The provider keys live in `deploy/worker.env`, which only the `worker` service reads (`env_file`).
The `api`, `migrate` and `db` services never see them. `deploy/.env` holds only `DB_PASSWORD`
(and optional host paths) and is read by Docker Compose for variable substitution.
Both files are git-ignored; never commit them.

The worker runs with `init: true` and `stop_grace_period: 30s`: `docker compose stop worker` delivers SIGTERM to
Python, which stops a running pipeline child and puts its job back in the queue (no attempt counted); the run
continues from its checkpoint when the worker starts again. One run may take at most
`RESEARCH_WEB_JOB_TIMEOUT_SECONDS` (default 3600; set it in `deploy/worker.env`), after which it fails with
`the run timed out after N s`. The pipeline child never reads a `.env` file.

## 2. First deployment

```bash
cp deploy/.env.example deploy/.env              # set DB_PASSWORD to a long random value
cp deploy/worker.env.example deploy/worker.env  # fill in the provider keys you are allowed to use
docker compose -f deploy/docker-compose.yml config   # check the merged file first (see section 6)
docker compose -f deploy/docker-compose.yml up -d --build
```

Create the first admin (the password is read from the environment variable, never from the command line):

```bash
docker compose -f deploy/docker-compose.yml run --rm \
  -e RESEARCH_WEB_ADMIN_PASSWORD='…' \
  api research-web create-admin --email admin@example.org --name "Admin"
```

Import existing run and eval folders (the worker is the service that can write the `runs` volume):

```bash
docker compose -f deploy/docker-compose.yml run --rm worker research-web import --all
```

Eval folders and gold files are bind-mounted from `../evals` and `../gold` relative to `deploy/`
(the repository's `evals/` and `gold/`); set `EVALS_DIR` and `GOLD_DIR` in `deploy/.env` to use other host paths.

## 3. TLS

The API is published only on `127.0.0.1:8000`. Put a reverse proxy (for example Caddy or nginx) in front of it
that terminates TLS and forwards to `127.0.0.1:8000`. The session cookie is `Secure`, so a login over plain HTTP
will not be kept. Set HSTS (`Strict-Transport-Security`) at the proxy.

## 4. Backups

- Database: `docker compose -f deploy/docker-compose.yml exec db pg_dump -U research research > research-$(date +%F).sql`
- Run folders: copy the `runs` volume, for example
  `docker run --rm -v research-agent_runs:/data/runs:ro -v "$PWD":/backup alpine tar czf /backup/runs-$(date +%F).tgz -C /data runs`

Back up both together: the database refers to run folders by path.

## 5. Provider policy

Only public titles and abstracts leave the company. The allowed providers are exactly the ones whose keys are
present in `deploy/worker.env`; leave a key empty to keep its provider out. The model ids in that file
(`RESEARCH_MODEL`, `RESEARCH_REVIEWER_A_MODEL`, `RESEARCH_REVIEWER_B_MODEL`, `RESEARCH_ADJUDICATOR_MODEL`)
must name providers whose keys are set. The Jev screening tier is used only when `TYPESAFE_API_KEY` is set.

## 6. What was not verified on the development machine

Docker is not installed on the development machine. The Dockerfile and the compose file were never built or
started there; `tests/test_web_deploy.py` checks them as data only (services, startup order, key isolation,
read-only mounts, loopback-only port, secure defaults, no secret values, unprivileged image).

On a Docker host, before the first `up`, run:

```bash
docker compose -f deploy/docker-compose.yml config
```

and expect it to print the merged file without errors (it fails if `DB_PASSWORD` is not set in `deploy/.env`
or `deploy/worker.env` is missing). Then run `up -d --build` and check that `api` becomes healthy
(`docker compose -f deploy/docker-compose.yml ps`).
