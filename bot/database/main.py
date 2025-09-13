import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, Engine, QueuePool
from sqlalchemy.orm import declarative_base, sessionmaker

from bot.database.dsn import dsn
from bot.misc import SingletonMeta


class Database(metaclass=SingletonMeta):
    BASE = declarative_base()

    def __init__(self):
        self.__engine: Engine = create_engine(
            dsn(),
            echo=False,  # Disable SQL logging (enable only for debug)
            pool_pre_ping=True,  # Check the connection before use
            future=True,  # Using SQLAlchemy 2.0 style

            # Settings for optimization
            poolclass=QueuePool,  # Connection pool type
            pool_size=20,  # Number of permanent connections
            max_overflow=40,  # Additional connections at peak load
            pool_timeout=30,  # Free connection timeout
            pool_recycle=3600,  # Re-create connections every hour

            # Additional optimizations
            connect_args={
                "connect_timeout": 10,
                "options": "-c statement_timeout=30000"  # 30 seconds per request
            }
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
