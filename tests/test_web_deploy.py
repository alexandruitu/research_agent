import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TYPESAFE_API_KEY", "RESEARCH_MODEL")


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text())


def test_services_and_startup_order(compose):
    services = compose["services"]
    assert set(services) == {"db", "migrate", "api", "worker", "web"}
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["worker"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert "healthcheck" in services["db"] and "healthcheck" in services["api"]


SECRET_SUFFIXES = ("_API_KEY", "_SECRET", "_TOKEN")
DEPLOY = ROOT / "deploy"


def env_names(service):
    """Variable names from `environment`, whether written as a mapping or as a list of NAME[=value]."""
    env = service.get("environment") or {}
    return set(env) if isinstance(env, dict) else {item.split("=", 1)[0] for item in env}


def volume_source(volume):
    """The host side of a volume, with a `${VAR:-default}` source read as its default."""
    if isinstance(volume, dict):
        return str(volume.get("source", ""))
    if volume.startswith("${"):
        variable = volume[2 : volume.index("}")]
        return variable.split(":-", 1)[1] if ":-" in variable else ""
    return volume.split(":", 1)[0]


def key_problems(service):
    """Every way a service could see the worker's provider keys."""
    problems = []
    if "env_file" in service:
        problems.append("reads an env_file")
    leaked = {n for n in env_names(service) if n in KEYS or n.endswith(SECRET_SUFFIXES)}
    if leaked:
        problems.append(f"carries {sorted(leaked)}")
    for volume in service.get("volumes") or []:
        source = volume_source(volume)
        if "/" not in source and not source.startswith("."):
            continue  # a named volume
        host = (DEPLOY / source).resolve()
        if host.name.endswith(".env") or any((path / ".env").is_relative_to(host) for path in (ROOT, DEPLOY)):
            problems.append(f"mounts {source}, which is or contains a .env file")
    return problems


def test_provider_keys_exist_only_in_the_worker(compose):
    for name in ("db", "migrate", "api", "web"):
        assert key_problems(compose["services"][name]) == [], name
    assert compose["services"]["worker"]["env_file"] == ["worker.env"]


@pytest.mark.parametrize(
    "service",
    [
        {"environment": ["RESEARCH_RUNS_DIR=/data/runs", "ANTHROPIC_API_KEY"]},
        {"environment": {"MISTRAL_API_KEY": "${MISTRAL_API_KEY}"}},
        {"environment": ["HF_TOKEN=x"]},
        {"env_file": "worker.env"},
        {"volumes": ["./worker.env:/app/worker.env:ro"]},
        {"volumes": ["../.env:/app/.env:ro"]},
        {"volumes": ["..:/app:ro"]},
        {"volumes": ["${SRC:-..}:/app:ro"]},
        {"volumes": [{"type": "bind", "source": ".", "target": "/deploy"}]},
    ],
)
def test_the_key_check_catches_every_way_in(service):
    assert key_problems(service)


def test_the_worker_forwards_stop_signals_to_python(compose):
    """With `init`, docker stop's SIGTERM reaches the worker, which stops its child and requeues the job."""
    worker = compose["services"]["worker"]
    assert worker["init"] is True and worker["stop_grace_period"] == "30s"


def test_the_api_mounts_run_folders_read_only_and_the_worker_can_write_runs(compose):
    api_volumes = compose["services"]["api"]["volumes"]
    assert api_volumes and all(v.endswith(":ro") for v in api_volumes)
    worker_volumes = compose["services"]["worker"]["volumes"]
    assert any(v.startswith("runs:/data/runs") and not v.endswith(":ro") for v in worker_volumes)
    assert all(v.endswith(":ro") for v in worker_volumes if "/data/evals" in v or "/data/gold" in v)


def test_only_the_web_service_publishes_a_port_and_only_on_loopback(compose):
    for name, service in compose["services"].items():
        ports = service.get("ports", [])
        if name == "web":
            assert ports == ["127.0.0.1:8080:8080"]
        else:
            assert not ports, f"{name} must not publish ports; the browser reaches the API through nginx"
    assert compose["services"]["api"]["expose"] == ["8000"]


def test_secure_defaults_in_the_api_environment(compose):
    env = compose["services"]["api"]["environment"]
    assert env["RESEARCH_WEB_COOKIE_SECURE"] == "true" and env["RESEARCH_WEB_ALLOW_DEMO"] == "false"
    assert "0.0.0.0" in compose["services"]["api"]["command"]  # inside the container; only nginx reaches it


def test_no_secret_value_is_written_into_any_deployment_file():
    for path in (COMPOSE, ROOT / "deploy" / ".env.example", ROOT / "deploy" / "worker.env.example"):
        text = path.read_text()
        assert not re.search(r"sk-[A-Za-z0-9_-]{8,}|apikey_[0-9a-f]{8,}", text), path
    for name in ("deploy/.env.example", "deploy/worker.env.example"):
        for line in (ROOT / name).read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                assert value == "" or key in {
                    "RESEARCH_MODEL",
                    "RESEARCH_REVIEWER_A_MODEL",
                    "RESEARCH_REVIEWER_B_MODEL",
                    "RESEARCH_ADJUDICATOR_MODEL",
                }, f"{name}: {key} must be empty in the example"


def test_dockerfile_is_unprivileged_and_never_copies_env_files():
    text = (ROOT / "deploy" / "Dockerfile").read_text()
    assert "USER app" in text and not re.search(r"COPY[^\n]*\.env", text)
    ignore = (ROOT / ".dockerignore").read_text().split()
    assert {".env", ".venv", ".git", "runs", "evals", "gold", ".web-dev"} <= set(ignore)


def test_the_web_package_data_files_ship_in_the_wheel():
    """hatchling puts every file under `packages` into the wheel unless an exclusion or a .gitignore pattern
    drops it; the installed (non-editable) app needs stages.yaml and the migration template at runtime."""
    import fnmatch
    import tomllib

    wheel = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/research_agent"]
    assert not {"include", "exclude", "only-include", "sources", "artifacts"} & set(wheel)
    patterns = [
        line.strip().rstrip("/")
        for line in (ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    for relative in (
        "src/research_agent/web/stages.yaml",
        "src/research_agent/web/db/migrations/script.py.mako",
    ):
        assert (ROOT / relative).is_file(), relative
        parts = relative.split("/")
        for pattern in patterns:
            assert not fnmatch.fnmatch(relative, pattern), (relative, pattern)
            assert not any(fnmatch.fnmatch(part, pattern) for part in parts), (relative, pattern)


def test_the_web_container_is_unprivileged_and_read_only(compose):
    web = compose["services"]["web"]
    assert web["read_only"] is True and web["tmpfs"] == ["/tmp"]
    assert "env_file" not in web and not (web.get("environment") or {})
    text = (ROOT / "deploy" / "Dockerfile.web").read_text()
    assert "nginx-unprivileged" in text and "npm ci" in text and not re.search(r"COPY[^\n]*\.env", text)


NGINX = ROOT / "deploy" / "nginx.conf"


def test_nginx_serves_the_app_and_proxies_only_the_api():
    text = NGINX.read_text()
    assert "listen 8080;" in text and "server_tokens off;" in text
    assert "proxy_pass http://api:8000;" in text
    assert "try_files $uri /index.html;" in text  # client-side routes
    assert text.count("proxy_pass") == 1


def test_nginx_csp_is_strict():
    text = NGINX.read_text()
    policy = re.search(r"add_header Content-Security-Policy \"([^\"]+)\" always;", text).group(1)
    for directive in (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "object-src 'none'",
    ):
        assert directive in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy and "*" not in policy
    for header in ("X-Content-Type-Options nosniff", "Referrer-Policy no-referrer", "X-Frame-Options DENY"):
        assert f"add_header {header} always;" in text


def test_nginx_locations_do_not_reset_the_security_headers():
    # nginx drops inherited add_header directives in any block that defines its own; keep them at server level only.
    text = NGINX.read_text()
    for block in re.findall(r"location[^{]*\{[^}]*\}", text):
        assert "add_header" not in block, block
    api_block = re.search(r"location /api/ \{[^}]*\}", text).group(0)
    for name in ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options"):
        assert f"proxy_hide_header {name};" in api_block  # one source of truth at the edge


CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_runs_every_check_and_needs_no_secrets():
    text = CI.read_text()
    workflow = yaml.safe_load(text)
    assert set(workflow["jobs"]) == {"python", "web", "e2e", "docker"}
    assert "secrets." not in text, "no check may need an API key"
    assert "pip-audit" in text and "npm audit" in text
    web = " ".join(step.get("run", "") for step in workflow["jobs"]["web"]["steps"])
    for command in (
        "npm ci",
        "npm run gen:api",
        "git diff --exit-code src/api/schema.d.ts",
        "npm run typecheck",
        "npm run lint",
        "npm test",
        "npm run build",
    ):
        assert command in web, command
    python = " ".join(step.get("run", "") for step in workflow["jobs"]["python"]["steps"])
    assert "ruff check ." in python and "pytest" in python
    docker = " ".join(step.get("run", "") for step in workflow["jobs"]["docker"]["steps"])
    assert "docker compose -f deploy/docker-compose.yml config" in docker and "deploy/Dockerfile.web" in docker
    assert workflow["jobs"]["e2e"]["env"]["PYTHON_DOTENV_DISABLED"] == "1"
