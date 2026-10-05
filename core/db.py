"""The bot's SQLite database: one shared connection, explicit transactions and numbered migration files."""

import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import overload

log = logging.getLogger("bot")

MIGRATION_FILE = re.compile(r"^(\d+)_.*\.sql$")
# Each migration file runs in one transaction together with the user_version bump, so a file must not contain its own
# BEGIN or COMMIT, and PRAGMA foreign_keys has no effect in it
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_conn: sqlite3.Connection | None = None


def init(path: str | Path, migrations_dir: str | Path = MIGRATIONS_DIR) -> None:
    global _conn

    conn = connect(path)
    try:
        migrate(conn, migrations_dir)
    except Exception:
        conn.close()
        raise
    _conn = conn


def close() -> None:
    global _conn

    if _conn is not None:
        _conn.close()
        _conn = None


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Run the queries in the block in one transaction. Never await inside it, because all code shares one connection.

    Only use it on the event loop thread, not in asyncio.to_thread work, because the connection belongs to that thread.
    """
    if _conn is None:
        raise RuntimeError("Database not initialised, call db.init() first")

    _conn.execute("BEGIN IMMEDIATE")
    try:
        yield _conn
        _conn.commit()
    except BaseException:
        _conn.rollback()
        raise


def time_text(moment: datetime | None) -> str | None:
    """Times are stored as UTC ISO-8601 strings."""
    return None if moment is None else moment.astimezone(UTC).isoformat()


@overload
def parse_time(text: str) -> datetime: ...


@overload
def parse_time(text: None) -> None: ...


def parse_time(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Without implicit transactions, so transaction() can open them explicitly
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrations(migrations_dir: str | Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for file in Path(migrations_dir).iterdir():
        match = MIGRATION_FILE.match(file.name)
        if match:
            found.append((int(match.group(1)), file))
    found.sort()

    versions = [version for version, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError(f"Duplicate database migration numbers in {migrations_dir}")
    return found


def migrate(conn: sqlite3.Connection, migrations_dir: str | Path) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    migrations = _migrations(migrations_dir)

    latest = migrations[-1][0] if migrations else 0
    if current > latest:
        log.warning(f"Database is at version {current}, newer than the latest migration {latest}")

    for version, file in migrations:
        if version <= current:
            continue

        try:
            conn.executescript(f"BEGIN;\n{file.read_text()}\n;PRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            log.critical(f"Database migration {file.name} failed, rolled back")
            raise
        log.info(f"Applied database migration {file.name}")
