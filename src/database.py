# src/database.py
from __future__ import annotations

import logging
import time
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from .config import settings
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

logger = logging.getLogger(__name__)

# Récupère l'URL SQLAlchemy finale
DB_URL = getattr(settings, "sqlalchemy_url", None) or getattr(settings, "DATABASE_URL", None)
if not DB_URL:
    raise RuntimeError("No database URL provided (sqlalchemy_url / DATABASE_URL missing).")

# Crée l'engine (ne teste pas la connectivité à ce stade)
engine = create_engine(
    DB_URL,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    echo=False,
    future=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # ✅ évite les SELECT implicites après commit
    future=True,
)

Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def wait_for_db(max_attempts: int = 10, base_sleep: float = 0.5, max_sleep: float = 5.0) -> None:
    """
    Tente une connexion simple avec backoff exponentiel.
    """
    attempt = 0
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            return
        except OperationalError as e:
            attempt += 1
            if attempt >= max_attempts:
                logger.exception("Database is not reachable after retries")
                raise
            sleep_s = min(max_sleep, base_sleep * (2 ** (attempt - 1)))
            logger.warning(f"DB not ready yet (attempt {attempt}/{max_attempts}): {e}. Retrying in {sleep_s:.1f}s…")
            time.sleep(sleep_s)


def test_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection successful")
        return True
    except SQLAlchemyError as e:
        logger.error(f"Database connection failed: {e}")
        return False


def init_database() -> None:
    """
    Initialise les extensions requises (idempotent).
    ⚠️ Nécessite des droits superuser pour CREATE EXTENSION (user 'postgres' conseillé).
    """
    try:
        with engine.begin() as conn:
            # Extensions
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "vector"'))  # <- CORRECT (pas "pgvector")
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))
        logger.info("Database extensions initialized successfully")
    except SQLAlchemyError as e:
        logger.error(f"Failed to initialize database: {e}")


# Optionnel : appeler ces helpers depuis ton startup FastAPI
# Exemple dans src/main.py:
#
# @app.on_event("startup")
# def on_startup():
#     wait_for_db()
#     init_database()
