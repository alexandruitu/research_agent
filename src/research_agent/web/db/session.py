from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

POOL_RECYCLE_SECONDS = 1800  # reconnect before idle connections are dropped by a firewall or NAT


def make_engine(url, statement_timeout_ms=None):
    """`statement_timeout_ms` caps every statement on PostgreSQL (the API sets it, so one slow query cannot
    hold a request and a pooled connection for ever); the worker and migrations run without a cap."""
    connect_args = {}
    if statement_timeout_ms and url.startswith("postgresql"):
        connect_args["options"] = f"-c statement_timeout={int(statement_timeout_ms)}"
    return create_engine(url, pool_pre_ping=True, pool_recycle=POOL_RECYCLE_SECONDS, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
