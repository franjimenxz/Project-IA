import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from ia_mcp.configuration.adapters.sqlalchemy import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

DATABASE_URL = "DATABASE_URL"


def database_url() -> str:
    """Migration target: the configured option, else the environment.

    `alembic.ini` ships no DSN so a checkout never migrates one developer's
    database. Callers that set `sqlalchemy.url` programmatically -- every
    suite does -- keep winning over the environment.
    """
    configured = (config.get_main_option("sqlalchemy.url") or "").strip()
    if configured:
        return configured
    url = os.environ.get(DATABASE_URL, "").strip()
    if not url:
        raise RuntimeError(
            f"Set {DATABASE_URL} or alembic's sqlalchemy.url before migrating."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(), target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = dict(config.get_section(config.config_ini_section, {}))
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
