import asyncio
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path, encoding='utf-8')

from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

import bot.database.models.main  # noqa: F401
from bot.database.main import Database
from bot.database.dsn import dsn

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Database.BASE.metadata


def get_url() -> str:
    url = dsn()
    return url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    connectable = create_async_engine(dsn(), poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
