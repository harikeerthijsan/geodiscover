"""Load the bundled discovery snapshot into the engine database on first boot.

The repository ships a gzip-compressed SQLite snapshot of the data already
fetched from the providers — the ~41k ``provider_places`` rows, the area sweeps
and their resolved clusters, the demo project and the administrator account. On a
fresh deployment, in particular the empty PostgreSQL database Railway provisions,
this copies that snapshot in so the application comes up populated rather than
blank.

The copy runs only when the engine database is empty, so repeating a deploy never
duplicates rows. After the copy, the administrator login is (re)created from the
environment so the operator can always sign in with the credentials they set.
"""
from __future__ import annotations

import gzip
import os
import shutil
import tempfile
import time
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError

from . import models  # noqa: F401 - registers every table on Base.metadata
from .auth import hash_password
from .config import ENGINE_SCHEMA, get_settings
from .database import Base, SessionLocal, engine, ensure_schema, is_postgres
from .models import ProviderPlace, User, UserRole

settings = get_settings()

#: Names searched for when ``seed_db_path`` is not set, preferring the compressed one.
SNAPSHOT_NAMES = ("discovery_engine_seed.db.gz", "discovery_engine_seed.db")
_BATCH = 1000


def wait_for_db(seconds: int | None = None) -> None:
    """Block until the database answers a trivial query, so boot survives a slow start."""
    deadline = settings.db_wait_seconds if seconds is None else seconds
    waited = 0.0
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            if waited >= deadline:
                raise
            print(f"Database not ready yet; retrying ({int(waited)}s/{deadline}s)...")
            time.sleep(2.0)
            waited += 2.0


def _snapshot_path() -> Path | None:
    if settings.seed_db_path:
        candidate = Path(settings.seed_db_path)
        return candidate if candidate.exists() else None
    package = Path(__file__).resolve().parent
    roots = [package, package.parent, Path.cwd(), Path("/app")]
    for root in roots:
        for name in SNAPSHOT_NAMES:
            candidate = root / name
            if candidate.exists():
                return candidate
    return None


def _as_sqlite_file(path: Path) -> tuple[str, str | None]:
    """Return a readable SQLite path, decompressing a ``.gz`` snapshot to a temp file.

    The second element is the temp file to delete afterwards, or ``None`` when the
    snapshot was already an uncompressed database used in place.
    """
    if path.suffix == ".gz":
        handle = tempfile.NamedTemporaryFile(prefix="geodiscover_seed_", suffix=".db", delete=False)
        handle.close()
        with gzip.open(path, "rb") as src, open(handle.name, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return handle.name, handle.name
    return str(path), None


def _target_has_data() -> bool:
    with engine.connect() as conn:
        for table in (User.__table__, ProviderPlace.__table__):
            count = conn.execute(select(func.count()).select_from(table)).scalar() or 0
            if count:
                return True
    return False


def _fix_sequences(conn, table_names) -> None:
    """Advance each Postgres id sequence past the explicit ids just inserted.

    Rows are copied with their original primary keys, so the SERIAL sequence still
    points at 1 and the next organic insert would collide. This realigns it.
    """
    for table in Base.metadata.sorted_tables:
        if table.name not in table_names:
            continue
        pk = list(table.primary_key.columns)
        if len(pk) != 1:
            continue
        column = pk[0]
        sequence = conn.execute(
            text("SELECT pg_get_serial_sequence(:t, :c)"),
            {"t": f"{ENGINE_SCHEMA}.{table.name}", "c": column.name},
        ).scalar()
        if not sequence:
            continue
        qualified = f'"{ENGINE_SCHEMA}"."{table.name}"'
        conn.execute(
            text(
                f"SELECT setval('{sequence}', "
                f"GREATEST((SELECT COALESCE(MAX({column.name}), 1) FROM {qualified}), 1))"
            )
        )


def copy_snapshot() -> dict[str, int]:
    """Copy every table from the bundled snapshot into the engine database.

    Only runs when the engine is empty. Returns ``{table: rows_copied}``.
    """
    path = _snapshot_path()
    if path is None:
        print("No discovery snapshot bundled; the engine starts empty.")
        return {}
    if _target_has_data():
        print("Engine already holds data; skipping snapshot load.")
        return {}

    sqlite_path, temp_to_clean = _as_sqlite_file(path)
    source = create_engine(f"sqlite:///{sqlite_path}", future=True)
    copied: dict[str, int] = {}
    try:
        with source.connect() as src, engine.begin() as dst:
            existing = set(source.dialect.get_table_names(src))
            for table in Base.metadata.sorted_tables:
                if table.name not in existing:
                    continue
                result = src.execution_options(stream_results=True).execute(select(table))
                total = 0
                batch: list[dict] = []
                for row in result.mappings():
                    batch.append(dict(row))
                    if len(batch) >= _BATCH:
                        dst.execute(table.insert(), batch)
                        total += len(batch)
                        batch = []
                if batch:
                    dst.execute(table.insert(), batch)
                    total += len(batch)
                if total:
                    copied[table.name] = total
            if is_postgres:
                _fix_sequences(dst, set(copied))
    finally:
        source.dispose()
        if temp_to_clean:
            try:
                os.unlink(temp_to_clean)
            except OSError:
                pass

    summary = ", ".join(f"{name}={rows}" for name, rows in copied.items())
    print(f"Loaded {sum(copied.values())} rows from {path.name} into the engine ({summary}).")
    return copied


def ensure_admin() -> None:
    """Create or refresh the administrator login from the environment."""
    db = SessionLocal()
    try:
        email = settings.demo_admin_email
        password_hash = hash_password(settings.demo_admin_password)
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None:
            db.add(
                User(
                    email=email,
                    full_name="JSAN GeoDiscover Administrator",
                    password_hash=password_hash,
                    role=UserRole.SUPER_ADMIN,
                    is_active=True,
                )
            )
            print(f"Created administrator {email}.")
        else:
            user.password_hash = password_hash
            user.role = UserRole.SUPER_ADMIN
            user.is_active = True
            print(f"Refreshed administrator {email} from the environment.")
        db.commit()
    finally:
        db.close()


def run_seed() -> None:
    """Full first-boot sequence: wait, build schema, load snapshot, ensure the admin."""
    wait_for_db()
    ensure_schema()
    Base.metadata.create_all(bind=engine)
    try:
        from .schema_sync import sync

        sync(apply=True)
    except Exception as exc:  # schema drift reconciliation is best-effort
        print(f"Schema sync skipped: {exc}")
    if settings.seed_on_boot:
        copy_snapshot()
    ensure_admin()


if __name__ == "__main__":
    run_seed()
