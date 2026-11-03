# Install with Docker on one LAN machine

Everything runs from the repository root. Design summary: `docs/deployment.md`.

## 1. Requirements

- A Linux machine (x86_64 or arm64) on the LAN, 2 CPU / 4 GB RAM / 20 GB disk or more.
- Docker Engine 24+ with the Compose plugin v2.24+ (`docker compose version`).
- A name or IP the browsers will use (e.g. `research.lan` in the LAN DNS, or `192.168.1.20`).
- Outbound HTTPS from the machine (directly or via a proxy) to the LLM providers and search APIs.

## 2. Install

```bash
git clone <repo-url> research_agent && cd research_agent
cp deploy/.env.example deploy/.env && chmod 600 deploy/.env
```

Edit `deploy/.env`:

| Variable | Value |
|---|---|
| `RESEARCH_SECRETS_KEY` | `python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` (or the `docker run` variant in the file). Keep a copy outside the server. |
| `DB_PASSWORD` | `openssl rand -hex 24` |
| `RESEARCH_WEB_ADMIN_EMAIL`, `RESEARCH_WEB_ADMIN_PASSWORD` | the first admin (password ≥ 12 characters) |
| `RESEARCH_WEB_SIGNUP_DOMAINS` | e.g. `example.org` (empty: nobody can sign up; admins add users) |
| `RESEARCH_WEB_CONTACT_EMAIL` | an address the public APIs (OpenAlex, Crossref, Unpaywall) can reach |
| `SITE_ADDRESS` | e.g. `research.lan, 192.168.1.20` |
| `CADDY_TLS` | `internal` (default) or `/certs/cert.pem /certs/key.pem` |
| `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` | only if outbound traffic needs a proxy (see section 9) |

No LLM key goes in this file: every user saves their own. Organisation-wide search-source keys (NCBI, S2,
IEEE, …) are optional: `cp deploy/worker.env.example deploy/worker.env` and fill in only those.

Check and start:

```bash
docker compose -f deploy/docker-compose.yml config -q      # no output = valid
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps             # db, api, proxy healthy; migrate exited 0
docker compose -f deploy/docker-compose.yml logs migrate   # "database is up to date", "created admin …"
```

## 3. First admin and sign-up

1. Open `https://<SITE_ADDRESS>/` and sign in with the admin email and password.
2. Remove `RESEARCH_WEB_ADMIN_PASSWORD` from `deploy/.env` (it is used only while no admin exists).
3. Check the sign-up domains on the Users page and the contact address in Settings → Sources. Later changes are made there;
   `deploy/.env` only seeds them on the very first start.
4. A missed bootstrap can be done by hand:
   `docker compose -f deploy/docker-compose.yml run --rm -e RESEARCH_WEB_ADMIN_PASSWORD='…' api research-web create-admin --email admin@example.org --name Admin`

## 4. Users add their keys

Each user signs up with an allowed email (or is added by an admin), then opens Settings → My keys and saves
the provider keys they are allowed to use, and Settings → My models to choose the models. Keys are encrypted
in the database with `RESEARCH_SECRETS_KEY` and decrypted only by the worker, for that user's own runs.

## 5. TLS

- **Internal CA (default):** Caddy issues a certificate from its own root. Browsers warn until the root is
  trusted. Export it: `docker compose -f deploy/docker-compose.yml cp proxy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt`
  and install it in the OS/browser trust store (or distribute it via your device management).
- **Your certificate:** put `cert.pem` (full chain) and `key.pem` in `deploy/certs/`, readable by the
  container, set `CADDY_TLS=/certs/cert.pem /certs/key.pem`, then
  `docker compose -f deploy/docker-compose.yml up -d proxy`.

The session cookie is `Secure`: plain HTTP only redirects.

## 6. Existing runs (optional)

```bash
docker compose -f deploy/docker-compose.yml run --rm worker research-web import --all
```

Eval and gold folders live in the `evals`/`gold` volumes; to use host folders set `EVALS_DIR`/`GOLD_DIR` in
`deploy/.env` to absolute paths.

## 7. Upgrade

```bash
scripts/backup.sh                                   # always first
git pull
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs migrate
```

`up` re-runs `migrate` (migrations under an advisory lock, repeat-safe) before `api` and `worker` start again.
A running job is requeued when the worker stops and resumes from its checkpoint.

## 8. Backup and restore

```bash
scripts/backup.sh                    # → deploy/backups/<YYYYmmdd-HHMMSS>/{db.dump,runs.tgz,cache.tgz,uploads.tgz,…}
```

Back up `deploy/.env` (it holds `RESEARCH_SECRETS_KEY`) separately and securely. Restore on the same or a
new machine (same `deploy/.env`):

```bash
B=deploy/backups/<stamp>
docker compose -f deploy/docker-compose.yml up -d db
docker compose -f deploy/docker-compose.yml stop api worker
docker compose -f deploy/docker-compose.yml exec -T db pg_restore -U research -d research --clean --if-exists < $B/db.dump
for v in runs cache uploads evals gold caddydata; do
  [ -f $B/$v.tgz ] && docker run --rm -v research-agent_$v:/v -v "$PWD/$B":/b alpine sh -c "rm -rf /v/* && tar xzf /b/$v.tgz -C /v && chown -R 10001:10001 /v"
done
docker compose -f deploy/docker-compose.yml up -d
```

(`caddydata` holds Caddy's internal CA; skip its `chown` concerns — Caddy runs as root in its image.)
The database refers to run folders by path, so restore the database and `runs` together.

## 9. Troubleshooting

- **Logs:** `docker compose -f deploy/docker-compose.yml logs -f api worker proxy` (keys are never logged).
- **`migrate` failed:** `logs migrate`; typical causes are a bad `RESEARCH_WEB_SIGNUP_DOMAINS` value or an
  admin email without a password. Fix `deploy/.env` and `up -d` again.
- **`set RESEARCH_SECRETS_KEY` / `not a valid Fernet key`:** generate one as in section 2.
- **Outbound proxy:** set `HTTPS_PROXY=http://proxy.corp:3128` and `NO_PROXY=localhost,127.0.0.1,db,api` (keep
  the service names in it), then `up -d worker`. Settings → Sources → Test checks a source end to end. A
  TLS-inspecting proxy needs its CA in the image (add it in `deploy/Dockerfile` with `update-ca-certificates`
  and set `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`).
- **Browser certificate warning:** trust Caddy's root (section 5) or provide a certificate.
- **Wrong host name:** the browser must use a name listed in `SITE_ADDRESS`; change it and `up -d proxy`.
- **Ports 80/443 taken:** set `HTTPS_PORT`/`HTTP_PORT` and use `https://host:<port>/`.
- **Smoke test** (throw-away stack on ports 18443/18080, removed afterwards): `scripts/docker_smoke.sh`.
