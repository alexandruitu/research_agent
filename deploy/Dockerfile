# One image for migrate, api and worker: the built React app plus the Python package (extras web + live).
# Build from the repository root: docker compose -f deploy/docker-compose.yml build
# No secret is baked in: keys come from deploy/.env at run time (see docs/deployment-docker.md).

# --- stage 1: the web app -----------------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- stage 2: Python runtime --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHON_DOTENV_DISABLED=1 \
    RESEARCH_WEB_STATIC_DIR=/app/web \
    RESEARCH_RUNS_DIR=/data/runs \
    RESEARCH_CACHE_DIR=/data/cache \
    RESEARCH_UPLOADS_DIR=/data/uploads \
    RESEARCH_EVALS_DIR=/data/evals \
    RESEARCH_GOLD_DIR=/data/gold
WORKDIR /app
# Dependencies first, from the hashed lock (deploy/requirements.lock.txt, regenerate with the command at its
# top): this layer stays cached until the lock changes. The app itself goes in after, without dependencies.
COPY deploy/requirements.lock.txt ./
RUN pip install --require-hashes -r requirements.lock.txt && rm requirements.lock.txt
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps '.[web,live]' && rm -rf /app/src /app/build
COPY --from=web /web/dist /app/web
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/runs /data/cache /data/uploads /data/evals /data/gold \
    && chown -R app:app /data
USER app
WORKDIR /data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"
CMD ["research-web", "serve", "--host", "0.0.0.0", "--port", "8000"]
