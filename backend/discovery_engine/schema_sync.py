"""Add columns that exist in the models but not yet in the database.

This project has no migration tool. ``Base.metadata.create_all`` creates missing
*tables* but never alters existing ones, so adding a column to a model leaves a
database created earlier silently out of date — and the failure shows up as a
confusing "no such column" at query time.

This reconciles the two by issuing ALTER TABLE ADD COLUMN for anything missing.
That is the only schema change it makes: it never drops or retypes a column, and it
never touches data. Anything beyond adding a column needs a real migration.

    python -m app.schema_sync            # report and apply
    python -m app.schema_sync --check    # report only, exit 1 if drift found
"""
from __future__ import annotations

import sys

from sqlalchemy import inspect, text

from .database import Base, engine
from . import models  # noqa: F401  - imported for its side effect of registering tables


def _column_ddl(column) -> str:
    ddl_type = column.type.compile(dialect=engine.dialect)
    default = ""
    if isinstance(column.default, type(None)):
        pass
    elif getattr(column.default, "is_scalar", False):
        value = column.default.arg
        if isinstance(value, str):
            default = f" DEFAULT '{value}'"
        elif isinstance(value, bool):
            default = f" DEFAULT {1 if value else 0}"
        elif isinstance(value, (int, float)):
            default = f" DEFAULT {value}"
    # Added columns must be nullable: existing rows have no value for them.
    return f"{column.name} {ddl_type}{default}"


def find_drift() -> list[tuple[str, str]]:
    """Return (table, column) pairs present in the models but missing in the database."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing: list[tuple[str, str]] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all handles whole missing tables
        present = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in present:
                missing.append((table.name, column.name))
    return missing


def sync(apply: bool = True) -> list[tuple[str, str]]:
    Base.metadata.create_all(bind=engine)
    drift = find_drift()
    if not drift:
        return []
    if not apply:
        return drift

    with engine.begin() as connection:
        for table_name, column_name in drift:
            table = Base.metadata.tables[table_name]
            column = table.columns[column_name]
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {_column_ddl(column)}"))
    return drift


def main() -> int:
    check_only = "--check" in sys.argv
    drift = sync(apply=not check_only)
    if not drift:
        print("Schema is up to date.")
        return 0
    verb = "Missing" if check_only else "Added"
    for table_name, column_name in drift:
        print(f"{verb}: {table_name}.{column_name}")
    if check_only:
        print(f"\n{len(drift)} column(s) missing. Run: python -m app.schema_sync")
        return 1
    print(f"\n{len(drift)} column(s) added.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
