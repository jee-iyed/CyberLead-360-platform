"""Engine creation, session factory, transaction scope and migrations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cyberlead360.config.logging import get_logger
from cyberlead360.config.settings import PROJECT_ROOT, Settings, get_settings

log = get_logger("database")


def create_db_engine(url: str, echo: bool = False) -> Engine:
    """Create an engine. SQLite gets foreign keys enforced and a sane journal mode."""
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            engine = create_engine(url, echo=echo, connect_args=connect_args, poolclass=StaticPool)
        else:
            db_path = url.removeprefix("sqlite:///")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(url, echo=echo, connect_args=connect_args)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores FKs unless enabled
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        return engine
    return create_engine(url, echo=echo, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Unit of work: commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_migrations(database_url: str | None = None) -> None:
    """Apply Alembic migrations up to ``head`` programmatically."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
    log.info("database migrated to head")


def schema_is_initialized(engine: Engine) -> bool:
    return inspect(engine).has_table("companies")


class Database:
    """Holds the engine and session factory for one database URL."""

    def __init__(self, settings: Settings | None = None, url: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.url = url or self.settings.database_url
        self.engine = create_db_engine(self.url, echo=self.settings.sql_echo)
        self.session_factory = make_session_factory(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with session_scope(self.session_factory) as s:
            yield s

    def ensure_schema(self) -> None:
        """Run migrations when enabled; otherwise require an initialized schema."""
        if self.settings.auto_migrate:
            run_migrations(self.url)
        elif not schema_is_initialized(self.engine):
            raise RuntimeError(
                "Database schema missing. Run: uv run python scripts/initialize_database.py"
            )
