import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from bot.database.dsn import dsn
from bot.misc import SingletonMeta


class Database(metaclass=SingletonMeta):
    BASE = declarative_base()

    def __init__(self):
        self.__engine: AsyncEngine = create_async_engine(
            dsn(),
            echo=False,
            pool_pre_ping=True,

            pool_size=20,
            max_overflow=40,
            pool_timeout=30,
            pool_recycle=3600,

            connect_args={
                "timeout": 10,
                "command_timeout": 30,
                "server_settings": {
                    "lc_messages": "C",
                },
            },
        )

        logging.info(f"Database pool initialized: size={20}, max_overflow={40}")

        self.__SessionLocal = async_sessionmaker(
            bind=self.__engine,
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    @asynccontextmanager
    async def session(self):
        """Async contextual session: guaranteed to close/rollback on error."""
        async with self.__SessionLocal() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    @property
    def engine(self) -> AsyncEngine:
        return self.__engine

    async def dispose(self):
        """Dispose of the connection pool."""
        await self.__engine.dispose()
