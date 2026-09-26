from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).with_name("migrations")


def alembic_config(url):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url, revision="head"):
    command.upgrade(alembic_config(url), revision)
