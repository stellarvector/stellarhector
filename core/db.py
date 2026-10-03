import logging
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

MIGRATION_FILE = re.compile(r"^(\d+)_.*\.sql$")
# Each migration file runs inside one transaction together with the user_version bump,
# so a file must not contain its own BEGIN/COMMIT, and PRAGMA foreign_keys has no effect in it
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
DEFAULT_PATH = "./data/stellarhector.db"

_conn = None


def init(path=DEFAULT_PATH, migrations_dir=MIGRATIONS_DIR):
    global _conn

    conn = connect(path)
    try:
        migrate(conn, migrations_dir)
    except Exception:
        conn.close()
        raise
    _conn = conn


def close():
    global _conn

    if _conn is not None:
        _conn.close()
        _conn = None


@contextmanager
def transaction():
    """Run queries in one transaction. Never await inside it: all code shares one connection.

    Only call it from the event loop thread (not from asyncio.to_thread work): the connection belongs to that thread.
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


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: no implicit transactions, we open them explicitly
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrations(migrations_dir):
    found = []
    for file in Path(migrations_dir).iterdir():
        match = MIGRATION_FILE.match(file.name)
        if match:
            found.append((int(match.group(1)), file))
    found.sort()

    versions = [version for version, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError(f"Duplicate database migration numbers in {migrations_dir}")
    return found


def migrate(conn, migrations_dir):
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    migrations = _migrations(migrations_dir)

    latest = migrations[-1][0] if migrations else 0
    if current > latest:
        logging.getLogger("bot").warning(f"Database is at version {current}, newer than the latest migration {latest}")

    for version, file in migrations:
        if version <= current:
            continue

        try:
            conn.executescript(f"BEGIN;\n{file.read_text()}\n;PRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            logging.getLogger("bot").critical(f"Database migration {file.name} failed, rolled back")
            raise
        logging.getLogger("bot").info(f"Applied database migration {file.name}")
