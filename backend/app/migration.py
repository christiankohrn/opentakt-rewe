"""Offene Alembic-Stände beim Start anwenden."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import get_settings
from app.db import Base, get_engine


def alembic_konfiguration() -> Config:
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def migrationen_anwenden() -> None:
    import app.models  # noqa: F401

    engine = get_engine()
    config = alembic_konfiguration()
    if engine.dialect.name == "sqlite":
        tabellen = set(inspect(engine).get_table_names())
        if "alembic_version" not in tabellen:
            Base.metadata.create_all(engine)
            command.stamp(config, "head")
            return
    command.upgrade(config, "head")

