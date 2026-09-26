import os

from alembic import context
from sqlalchemy import create_engine

from research_agent.web.db.models import Base

config = context.config
target_metadata = Base.metadata


def _url():
    return config.get_main_option("sqlalchemy.url") or os.environ["RESEARCH_WEB_DATABASE_URL"]


def run_migrations_online():
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
