"""research-web: migrate, create-admin, import, openapi and a local dev server."""

import argparse
import getpass
import json
import os
import signal
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from .api.app import create_app
from .auth import AuthError, create_user
from .db.migrate import upgrade
from .db.session import make_engine, make_session_factory
from .importer.common import ImportFailed
from .importer.evals import import_eval_run
from .importer.research import import_research_run
from .runner import sanitize_error
from .settings import SECRETS_KEY_ENV, load_settings
from .worker import Worker


def detect_kind(folder):
    folder = Path(folder)
    if (folder / "report.json").is_file():
        return "research"
    if (folder / "manifest.json").is_file() and (folder / "metrics.json").is_file():
        return "eval"
    return None


def find_import_targets(settings):
    targets = []
    for root in (settings.runs_dir, settings.evals_dir):
        if root.is_dir():
            for child in sorted(root.iterdir()):
                kind = detect_kind(child) if child.is_dir() else None
                if kind:
                    targets.append((kind, child))
    return targets


def run_imports(settings, targets):
    """Import each folder in its own transaction; a failure is reported and does not stop the others."""
    factory = make_session_factory(make_engine(settings.database_url))
    failures = 0
    for kind, path in targets:
        with factory() as db:
            try:
                if kind == "research":
                    result = import_research_run(db, path)
                else:
                    result = import_eval_run(db, path, gold_dir=settings.gold_dir)
                db.commit()
                print(f"{result.status:9} {kind:8} {path.name}")
                for warning in result.warnings:
                    print(f"          warning: {warning}")
            except ImportFailed as exc:
                db.rollback()
                failures += 1
                print(f"FAILED    {kind:8} {path.name}: {exc}")
            except Exception as exc:  # noqa: BLE001 -- one broken folder must not stop the others
                db.rollback()
                failures += 1
                print(f"FAILED    {kind:8} {path.name}: {sanitize_error(exc)}")
    return 1 if failures else 0


def cmd_import(args, settings):
    if args.all:
        targets = find_import_targets(settings)
    else:
        targets = []
        for raw in args.paths:
            kind = detect_kind(raw)
            if kind is None:
                print(
                    f"FAILED    unknown   {raw}: neither a research run (report.json)"
                    " nor an eval run (manifest.json + metrics.json)"
                )
                return 1
            targets.append((kind, Path(raw).resolve()))
    return run_imports(settings, targets)


def read_password():
    password = os.environ.get("RESEARCH_WEB_ADMIN_PASSWORD")
    if password:
        return password
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat: "):
        raise AuthError("passwords do not match")
    return first


def ensure_admin(settings, email, name):
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        user = create_user(
            db,
            email=email,
            name=name,
            role="admin",
            password=read_password(),
            min_password_length=settings.min_password_length,
        )
        db.commit()
        return user.email


def cmd_create_admin(args, settings):
    try:
        print(f"created admin {ensure_admin(settings, args.email, args.name)}")
    except AuthError as exc:
        print(f"FAILED: {exc}")
        return 1
    return 0


def cmd_openapi(args, settings):
    Path(args.output).write_text(json.dumps(create_app(settings).openapi(), indent=2))
    print(f"wrote {args.output}")
    return 0


def cmd_migrate(args, settings):
    upgrade(settings.database_url)
    print("database is up to date")
    return 0


BOOTSTRAP_LOCK = 0x5245_5341  # pg advisory lock id: one bootstrap at a time, even if two containers start


def cmd_bootstrap(args, settings):
    """Container start-up, safe to repeat: migrations under an advisory lock, then (only when the environment
    asks and nothing is set yet) the first admin, the sign-up domains and the contact address."""
    import sqlalchemy as sa

    from .api.schemas import SettingsPatch
    from .db.models import User
    from .fields import settings_row

    env = os.environ
    try:
        patch = SettingsPatch(
            signup_domains=[
                d for d in env.get("RESEARCH_WEB_SIGNUP_DOMAINS", "").replace(",", " ").split() if d
            ],
            contact_email=env.get("RESEARCH_WEB_CONTACT_EMAIL", "").strip() or None,
        )
    except ValueError as exc:
        print(
            "FAILED: RESEARCH_WEB_SIGNUP_DOMAINS or RESEARCH_WEB_CONTACT_EMAIL: " + " ".join(str(exc).split())
        )
        return 1
    engine = make_engine(settings.database_url)
    try:
        with engine.connect() as lock:
            lock.execute(sa.text("SELECT pg_advisory_lock(:id)"), {"id": BOOTSTRAP_LOCK})
            try:
                upgrade(settings.database_url)
                print("database is up to date")
                factory = make_session_factory(engine)
                email = env.get("RESEARCH_WEB_ADMIN_EMAIL", "").strip()
                with factory() as db:
                    has_admin = db.scalar(sa.select(User.id).where(User.role == "admin").limit(1))
                if email and not has_admin:
                    if not env.get("RESEARCH_WEB_ADMIN_PASSWORD"):
                        print(
                            "FAILED: RESEARCH_WEB_ADMIN_EMAIL is set but RESEARCH_WEB_ADMIN_PASSWORD is empty"
                        )
                        return 1
                    try:
                        print(
                            f"created admin {ensure_admin(settings, email, env.get('RESEARCH_WEB_ADMIN_NAME') or 'Admin')}"
                        )
                    except AuthError as exc:
                        print(f"FAILED: {exc}")
                        return 1
                elif has_admin:
                    print("an admin exists; RESEARCH_WEB_ADMIN_* is ignored")
                with factory() as db:
                    row = settings_row(db)
                    if patch.signup_domains and not row.signup_domains:
                        row.signup_domains = patch.signup_domains
                        print("sign-up domains set: " + ", ".join(patch.signup_domains))
                    if patch.contact_email and not row.contact_email:
                        row.contact_email = patch.contact_email
                        print("contact address set")
                    db.commit()
            finally:
                lock.execute(sa.text("SELECT pg_advisory_unlock(:id)"), {"id": BOOTSTRAP_LOCK})
    finally:
        engine.dispose()
    return 0


def dev_secrets_key(folder):
    """The development server's Fernet key: RESEARCH_SECRETS_KEY when set, else `<folder>/secrets.key`, created
    (mode 600) on first use. Never written to .env and never printed."""
    from cryptography.fernet import Fernet

    if os.environ.get(SECRETS_KEY_ENV):
        return os.environ[SECRETS_KEY_ENV]
    path = Path(folder) / "secrets.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(Fernet.generate_key().decode())
    return path.read_text().strip()


def require_secrets_key(settings):
    if not settings.secrets_key:
        print(f"FAILED: set {SECRETS_KEY_ENV} (a Fernet key) in the server environment; users' keys need it")
        return False
    return True


def cmd_dev(args, settings):
    """Local development: an embedded PostgreSQL in .web-dev/, migrations, optional import, then the API."""
    import pgserver
    import uvicorn

    data = Path(args.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(data, cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    # Development mode (RESEARCH_WEB_DEV_MODE): only this command sets it. It lets the worker's .env keys stand
    # in for keys a user has not saved; `serve` and `worker` never do that.
    env = dict(
        os.environ,
        RESEARCH_WEB_DATABASE_URL=url,
        RESEARCH_WEB_COOKIE_SECURE="false",
        RESEARCH_WEB_DEV_MODE="true",
        **{SECRETS_KEY_ENV: dev_secrets_key(data.parent)},
    )
    if args.allow_demo:
        env["RESEARCH_WEB_ALLOW_DEMO"] = "true"
    dev_settings = load_settings(env)
    upgrade(url)
    if args.admin_email:
        try:
            print(f"created admin {ensure_admin(dev_settings, args.admin_email, args.admin_name)}")
        except AuthError as exc:
            print(f"admin not created: {exc}")
    if args.import_all:
        run_imports(dev_settings, find_import_targets(dev_settings))
    print(f"API on http://{args.host}:{args.port}/api/v1 (Ctrl-C to stop; data in {data})")
    if not args.with_worker:
        uvicorn.run(create_app(dev_settings), host=args.host, port=args.port, log_level="info")
        return 0
    # The worker runs pipeline children that need provider keys: load .env into this process's environment
    # (never into dev_settings or a log). Keys live only in .env, so it overrides stray shell variables
    # (e.g. an unrelated ANTHROPIC_API_KEY exported by the shell). PYTHON_DOTENV_DISABLED=1 turns this off.
    load_dotenv(override=True)
    worker = Worker(dev_settings, key_check=True)
    thread = threading.Thread(target=worker.run_forever, name="dev-worker")  # joined below, never abandoned
    with stop_on_signals(worker):  # uvicorn re-raises the signal it stopped on once it has shut down
        thread.start()
        print("worker started in this process")
        try:
            uvicorn.run(create_app(dev_settings), host=args.host, port=args.port, log_level="info")
        finally:
            worker.request_stop()  # a running child is stopped and its job goes back to the queue
            thread.join()
    return 0


def cmd_serve(args, settings):
    import uvicorn

    if not require_secrets_key(settings):
        return 1
    # Behind the reverse proxy every request comes from the proxy's address. Trusting its X-Forwarded-*
    # headers (and only its: see --forwarded-allow-ips) gives the per-IP rate limits the real client.
    uvicorn.run(
        create_app(settings),
        host=args.host,
        port=args.port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips=args.forwarded_allow_ips,
    )
    return 0


@contextmanager
def stop_on_signals(worker):
    """SIGTERM and SIGINT ask the worker to stop instead of killing the process: the pipeline child runs in
    its own session, so killing the worker would leave it running (and spending credits)."""
    handlers = {
        signum: signal.signal(signum, lambda *_: worker.request_stop())
        for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        yield
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def cmd_worker(args, settings):
    if not require_secrets_key(settings):
        return 1
    worker = Worker(settings, key_check=not args.once)
    with stop_on_signals(worker):
        if args.once:
            try:
                worker.drain()
            except Exception as exc:  # noqa: BLE001 -- CLI boundary: one redacted line, non-zero exit
                print("FAILED: " + " ".join(sanitize_error(exc).split()))
                return 1
            return 0
        print(f"worker {worker.worker_id} started (Ctrl-C to stop)")
        worker.run_forever()
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="research-web", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    sub.add_parser(
        "bootstrap",
        help="container start-up: migrate (locked), then first admin and sign-up domains from env",
    ).set_defaults(func=cmd_bootstrap)
    p = sub.add_parser(
        "create-admin", help="create an admin (password from RESEARCH_WEB_ADMIN_PASSWORD or a prompt)"
    )
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_create_admin)
    p = sub.add_parser("import", help="import run and eval folders into the database")
    p.add_argument("paths", nargs="*")
    p.add_argument("--all", action="store_true", help="every folder under the runs and evals directories")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("openapi", help="write the OpenAPI schema (used to generate the frontend types)")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_openapi)
    p = sub.add_parser("dev", help="local development server with an embedded PostgreSQL")
    p.add_argument("--data-dir", default=".web-dev/pgdata")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--admin-email")
    p.add_argument("--admin-name", default="Admin")
    p.add_argument("--import-all", action="store_true")
    p.add_argument("--with-worker", action="store_true", help="also run the job worker in this process")
    p.add_argument("--allow-demo", action="store_true", help="allow demo-mode runs (offline, no model calls)")
    p.set_defaults(func=cmd_dev)
    p = sub.add_parser("serve", help="run the API (behind a reverse proxy that terminates TLS)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument(
        "--forwarded-allow-ips",
        default=os.environ.get("RESEARCH_WEB_FORWARDED_ALLOW_IPS") or "127.0.0.1",
        help="addresses or networks (comma-separated) of the reverse proxy whose X-Forwarded-* headers are "
        "trusted; default 127.0.0.1 or RESEARCH_WEB_FORWARDED_ALLOW_IPS",
    )
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("worker", help="run the job worker (the only process that needs LLM provider keys)")
    p.add_argument("--once", action="store_true", help="process queued jobs, then exit")
    p.set_defaults(func=cmd_worker)
    return parser


def main(argv=None, settings=None):
    args = build_parser().parse_args(argv)
    if args.command == "import" and not args.all and not args.paths:
        print("give one or more folders, or --all")
        return 1
    if settings is None and args.command != "dev":
        settings = load_settings()
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
