from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import ENGINE_SCHEMA, normalise_database_url

from .config import get_settings

settings = get_settings()
url = normalise_database_url(settings.engine_database_url)
is_postgres = url.startswith("postgresql")

connect_args: dict = {}
engine_kwargs: dict = {}
if url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # The engine reuses table names from the customer schema (users, projects,
    # poi_candidates and others), so on a shared Postgres database it is
    # confined to its own schema instead of public.
    connect_args = {"options": f"-csearch_path={ENGINE_SCHEMA}"}
    engine_kwargs = {"pool_pre_ping": True, "pool_recycle": 300}

engine = create_engine(url, connect_args=connect_args, future=True, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def ensure_schema() -> None:
    """Create the engine's schema before any table is created inside it."""
    if not is_postgres:
        return
    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{ENGINE_SCHEMA}"'))
        connection.commit()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
