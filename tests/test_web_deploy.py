import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TYPESAFE_API_KEY", "RESEARCH_MODEL", "ELSEVIER_INSTTOKEN")
SOURCE_KEYS = (
    "NCBI_API_KEY",
    "S2_API_KEY",
    "OPENALEX_API_KEY",
    "CORE_API_KEY",
    "IEEE_API_KEY",
    "SPRINGER_API_KEY",
    "ELSEVIER_API_KEY",
    "ELSEVIER_INSTTOKEN",
    "RESEARCH_AGENT_CONTACT",
)


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text())


def test_services_and_startup_order(compose):
    services = compose["services"]
    assert set(services) == {"db", "migrate", "api", "worker", "proxy"}
    assert services["migrate"]["command"] == ["research-web", "bootstrap"]
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["worker"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["proxy"]["depends_on"]["api"]["condition"] == "service_healthy"
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


def test_no_service_sees_provider_keys(compose):
    """Users bring their own keys (encrypted in the database); no container gets provider keys."""
    for name, service in compose["services"].items():
        if name != "worker":
            assert key_problems(service) == [], name
    worker = compose["services"]["worker"]
    assert worker["env_file"] == [{"path": "worker.env", "required": False}]
    assert not {n for n in env_names(worker) if n in KEYS or n.endswith(SECRET_SUFFIXES)}
    example = (DEPLOY / "worker.env.example").read_text()
    for name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "TYPESAFE_API_KEY",
        "RESEARCH_MODEL",
    ):
        assert f"{name}=" not in example, name
    for name in SOURCE_KEYS:
        assert name == "RESEARCH_AGENT_CONTACT" or f"{name}=" in example, name


def test_dev_mode_and_demo_are_forced_off_and_secrets_key_is_required(compose):
    text = COMPOSE.read_text()
    assert "${RESEARCH_SECRETS_KEY:?" in text
    for name in ("migrate", "api", "worker"):
        env = compose["services"][name]["environment"]
        assert env["RESEARCH_WEB_DEV_MODE"] == "false" and env["RESEARCH_WEB_ALLOW_DEMO"] == "false"
    worker = compose["services"]["worker"]["environment"]
    assert {"HTTPS_PROXY", "NO_PROXY"} <= set(worker)
    assert "RESEARCH_WEB_ADMIN_PASSWORD" not in compose["services"]["api"]["environment"]


@pytest.mark.parametrize(
    "service",
    [
        {"environment": ["RESEARCH_RUNS_DIR=/data/runs", "ANTHROPIC_API_KEY"]},
        {"environment": {"MISTRAL_API_KEY": "${MISTRAL_API_KEY}"}},
        {"environment": ["HF_TOKEN=x"]},
        {"environment": ["ELSEVIER_INSTTOKEN=x"]},
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


def test_the_env_example_holds_no_provider_keys():
    text = (DEPLOY / ".env.example").read_text()
    for name in (*KEYS, *SOURCE_KEYS):
        assert f"{name}=" not in text, name


def test_the_worker_forwards_stop_signals_to_python(compose):
    """With `init`, docker stop's SIGTERM reaches the worker, which stops its child and requeues the job."""
    worker = compose["services"]["worker"]
    assert worker["init"] is True and worker["stop_grace_period"] == "30s"


def test_the_api_mounts_run_folders_read_only_and_the_worker_can_write_runs(compose):
    api_volumes = compose["services"]["api"]["volumes"]
    # the API writes only uploaded PDFs, into their own volume; runs, evals and gold stay read-only
    assert api_volumes and all(v.endswith(":ro") for v in api_volumes if not v.startswith("uploads:"))
    assert "uploads:/data/uploads" in api_volumes
    worker_volumes = compose["services"]["worker"]["volumes"]
    assert "uploads:/data/uploads:ro" in worker_volumes
    assert any(v.startswith("runs:/data/runs") and not v.endswith(":ro") for v in worker_volumes)
    assert all(v.endswith(":ro") for v in worker_volumes if "/data/evals" in v or "/data/gold" in v)


def test_only_the_proxy_publishes_ports(compose):
    for name, service in compose["services"].items():
        ports = service.get("ports", [])
        if name == "proxy":
            assert ports == ["${HTTPS_PORT:-443}:443", "${HTTP_PORT:-80}:80"]
        else:
            assert not ports, f"{name} must not publish ports; the browser reaches the API through Caddy"
    assert compose["services"]["api"]["expose"] == ["8000"]


def test_secure_defaults_in_the_api_environment(compose):
    env = compose["services"]["api"]["environment"]
    assert env["RESEARCH_WEB_COOKIE_SECURE"] == "true" and env["RESEARCH_WEB_ALLOW_DEMO"] == "false"
    assert "0.0.0.0" in compose["services"]["api"]["command"]  # inside the container; only Caddy reaches it


def test_no_secret_value_is_written_into_any_deployment_file():
    for path in (COMPOSE, ROOT / "deploy" / ".env.example", ROOT / "deploy" / "worker.env.example"):
        text = path.read_text()
        assert not re.search(r"sk-[A-Za-z0-9_-]{8,}|apikey_[0-9a-f]{8,}", text), path
    for name in ("deploy/.env.example", "deploy/worker.env.example"):
        for line in (ROOT / name).read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                assert value == "" or key in {"CADDY_TLS", "HTTPS_PORT", "HTTP_PORT"}, (
                    f"{name}: {key} must be empty in the example"
                )


def test_dockerfile_is_unprivileged_and_never_copies_env_files():
    text = (ROOT / "deploy" / "Dockerfile").read_text()
    assert "USER app" in text and not re.search(r"COPY[^\n]*\.env", text)
    assert "npm ci" in text and "AS web" in text and "'.[web,live]'" in text
    assert "PYTHON_DOTENV_DISABLED=1" in text and "RESEARCH_WEB_STATIC_DIR=/app/web" in text
    ignore = (ROOT / ".dockerignore").read_text().split()
    assert {".env", ".venv", ".git", "runs", "evals", "gold", ".web-dev"} <= set(ignore)


def test_caddy_terminates_tls_and_proxies_only_the_api():
    text = (DEPLOY / "Caddyfile").read_text()
    assert "tls {$CADDY_TLS}" in text and "Strict-Transport-Security" in text and "admin off" in text
    assert text.count("reverse_proxy api:8000") == 2 and text.count("reverse_proxy") == 2
    assert "max_size 31MB" in text and "max_size 1MB" in text
    assert "encode zstd gzip" in text


def test_app_containers_are_hardened_and_only_caddy_shares_the_edge_network(compose):
    services = compose["services"]
    for name in ("migrate", "api", "worker"):
        service = services[name]
        assert service["read_only"] is True and service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert any(t.startswith("/tmp") for t in service["tmpfs"]), name
    assert services["proxy"]["cap_add"] == ["NET_BIND_SERVICE"] and services["proxy"]["networks"] == ["edge"]
    assert [n for n, s in services.items() if "edge" in s.get("networks", [])] == ["api", "proxy"]
    subnet = compose["networks"]["edge"]["ipam"]["config"][0]["subnet"]
    # the API trusts X-Forwarded-For only from the edge network, so the per-IP limits see real clients
    assert services["api"]["environment"]["RESEARCH_WEB_FORWARDED_ALLOW_IPS"] == subnet


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
    assert "docker compose -f deploy/docker-compose.yml config" in docker and "deploy/Dockerfile" in docker
    assert workflow["jobs"]["e2e"]["env"]["PYTHON_DOTENV_DISABLED"] == "1"
