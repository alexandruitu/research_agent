"""research-web: migrate, create-admin, import, openapi and a local dev server."""

import argparse
import getpass
import json
import os
import sys
import threading
from pathlib import Path

from .api.app import create_app
from .auth import AuthError, create_user
from .db.migrate import upgrade
from .db.session import make_engine, make_session_factory
from .importer.common import ImportFailed
from .importer.evals import import_eval_run
from .importer.research import import_research_run
from .runner import sanitize_error
from .settings import load_settings
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


def cmd_dev(args, settings):
    """Local development: an embedded PostgreSQL in .web-dev/, migrations, optional import, then the API."""
    import pgserver
    import uvicorn

    data = Path(args.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(data, cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    env = dict(os.environ, RESEARCH_WEB_DATABASE_URL=url, RESEARCH_WEB_COOKIE_SECURE="false")
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
    stop = threading.Event()
    if args.with_worker:
        threading.Thread(
            target=Worker(dev_settings).run_forever,
            kwargs={"stop": stop.is_set},
            daemon=True,
            name="dev-worker",
        ).start()
        print("worker started in this process")
    try:
        uvicorn.run(create_app(dev_settings), host=args.host, port=args.port, log_level="info")
    finally:
        stop.set()
    return 0


def cmd_serve(args, settings):
    import uvicorn

    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="info")
    return 0


def cmd_worker(args, settings):
    worker = Worker(settings)
    if args.once:
        worker.drain()
        return 0
    print(f"worker {worker.worker_id} started (Ctrl-C to stop)")
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        pass
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="research-web", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
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
