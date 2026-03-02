import asyncio
import logging
from contextlib import contextmanager
from functools import wraps

import psycopg2
from sqlalchemy import create_engine, Engine, QueuePool
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from bot.database.dsn import dsn
from bot.misc import SingletonMeta


def run_sync(func):
    """Decorator: wraps a synchronous DB function to run in a thread pool executor,
    keeping the event loop free for other async operations."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    return wrapper


def _create_connection():
    """Custom connection factory that avoids UnicodeDecodeError on Windows.

    On Windows with Russian locale, PostgreSQL sends cp1251-encoded data during
    the connection handshake. psycopg2's C-level _connect() tries to decode it
    as UTF-8 and fails. Connecting with LATIN1 first (accepts any byte) bypasses
    this, then we switch to UTF-8 for all subsequent data exchange.
    """
    url = make_url(dsn())
    conn = psycopg2.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        password=url.password,
        connect_timeout=10,
        options="-c statement_timeout=30000 -c lc_messages=C",
        client_encoding="LATIN1",
    )
    conn.set_client_encoding('UTF8')
    return conn


class Database(metaclass=SingletonMeta):
    BASE = declarative_base()

    def __init__(self):
        self.__engine: Engine = create_engine(
            dsn(),
            echo=False,  # Disable SQL logging (enable only for debug)
            pool_pre_ping=True,  # Check the connection before use
            future=True,  # Using SQLAlchemy 2.0 style
            creator=_create_connection,  # Custom factory to handle Windows encoding

            # Settings for optimization
            poolclass=QueuePool,  # Connection pool type
            pool_size=20,  # Number of permanent connections
            max_overflow=40,  # Additional connections at peak load
            pool_timeout=30,  # Free connection timeout
            pool_recycle=3600,  # Re-create connections every hour
        )

        # Pool state logging
        logging.info(f"Database pool initialized: size={20}, max_overflow={40}")

        self.__SessionLocal = sessionmaker(bind=self.__engine, autoflush=False, autocommit=False, future=True,
                                           expire_on_commit=False)

    @contextmanager
    def session(self):
        """Contextual session: guaranteed to close/rollback on error."""
        db = self.__SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @property
    def engine(self) -> Engine:
        return self.__engine
