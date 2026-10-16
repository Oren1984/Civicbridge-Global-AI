"""Alembic environment. Migrations always run as the admin role, never as the runtime application role."""
from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  (register all tables)
from app.config import get_settings
from app.db import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(get_settings().admin_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
