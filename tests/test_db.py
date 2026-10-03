import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import db


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.migrations_dir = Path(self.tmp.name) / "migrations"
        self.migrations_dir.mkdir()
        self.db_path = Path(self.tmp.name) / "data" / "test.db"

    def add_migration(self, filename, sql):
        (self.migrations_dir / filename).write_text(sql)

    def open(self):
        conn = db.connect(self.db_path)
        self.addCleanup(conn.close)
        return conn

    def version(self, conn):
        return conn.execute("PRAGMA user_version").fetchone()[0]

    def test_fresh_database_migrates_to_latest_version(self):
        self.add_migration("0001_things.sql", "CREATE TABLE things (id INTEGER PRIMARY KEY);")
        self.add_migration("0002_more.sql", "ALTER TABLE things ADD COLUMN name TEXT;")
        conn = self.open()

        db.migrate(conn, self.migrations_dir)

        self.assertEqual(self.version(conn), 2)
        conn.execute("INSERT INTO things (id, name) VALUES (1, 'a')")

    def test_already_migrated_database_is_left_alone(self):
        self.add_migration("0001_things.sql", "CREATE TABLE things (id INTEGER PRIMARY KEY);")
        conn = self.open()
        db.migrate(conn, self.migrations_dir)
        conn.execute("INSERT INTO things (id) VALUES (1)")

        db.migrate(conn, self.migrations_dir)

        self.assertEqual(self.version(conn), 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM things").fetchone()[0], 1)

    def test_new_migration_upgrades_existing_database(self):
        self.add_migration("0001_things.sql", "CREATE TABLE things (id INTEGER PRIMARY KEY);")
        db.migrate(self.open(), self.migrations_dir)
        self.add_migration("0002_more.sql", "ALTER TABLE things ADD COLUMN name TEXT;")
        conn = self.open()

        db.migrate(conn, self.migrations_dir)

        self.assertEqual(self.version(conn), 2)
        conn.execute("INSERT INTO things (id, name) VALUES (1, 'a')")

    def test_migrations_apply_in_numeric_order(self):
        self.add_migration("10_rename.sql", "ALTER TABLE things RENAME TO stuff;")
        self.add_migration("9_things.sql", "CREATE TABLE things (id INTEGER PRIMARY KEY);")
        conn = self.open()

        db.migrate(conn, self.migrations_dir)

        self.assertEqual(self.version(conn), 10)
        conn.execute("SELECT * FROM stuff")

    def test_failing_migration_rolls_back_and_raises(self):
        self.add_migration("0001_things.sql", "CREATE TABLE things (id INTEGER PRIMARY KEY);")
        self.add_migration("0002_broken.sql", "CREATE TABLE half (id INTEGER);\nTHIS IS NOT SQL;")
        self.add_migration("0003_after.sql", "CREATE TABLE after (id INTEGER);")
        conn = self.open()

        with self.assertRaises(sqlite3.Error):
            db.migrate(conn, self.migrations_dir)

        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(self.version(conn), 1)
        self.assertEqual(tables, {"things"})
        self.assertFalse(conn.in_transaction)

    def test_duplicate_migration_numbers_raise(self):
        self.add_migration("0001_things.sql", "CREATE TABLE things (id INTEGER PRIMARY KEY);")
        self.add_migration("0001_other.sql", "CREATE TABLE other (id INTEGER PRIMARY KEY);")
        conn = self.open()

        with self.assertRaises(ValueError):
            db.migrate(conn, self.migrations_dir)

        self.assertEqual(self.version(conn), 0)


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        migrations_dir = Path(self.tmp.name) / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "0001_things.sql").write_text("CREATE TABLE things (id INTEGER PRIMARY KEY);")
        db.init(Path(self.tmp.name) / "test.db", migrations_dir)
        self.addCleanup(db.close)

    def count_things(self):
        with db.transaction() as conn:
            return conn.execute("SELECT COUNT(*) FROM things").fetchone()[0]

    def test_commits_on_success(self):
        with db.transaction() as conn:
            conn.execute("INSERT INTO things (id) VALUES (1)")

        self.assertEqual(self.count_things(), 1)

    def test_rolls_back_and_reraises_on_error(self):
        with self.assertRaises(RuntimeError):
            with db.transaction() as conn:
                conn.execute("INSERT INTO things (id) VALUES (1)")
                raise RuntimeError("boom")

        self.assertEqual(self.count_things(), 0)


class UninitialisedTest(unittest.TestCase):
    def test_transaction_before_init_raises_clear_error(self):
        with self.assertRaises(RuntimeError):
            with db.transaction():
                pass


class ShippedMigrationsTest(unittest.TestCase):
    def test_job_runs_table_exists_after_init(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)

        with db.transaction() as conn:
            conn.execute("INSERT INTO job_runs (name, last_run_at) VALUES ('tick', '2026-10-03T12:00:00+00:00')")
            row = conn.execute("SELECT last_run_at FROM job_runs WHERE name = 'tick'").fetchone()

        self.assertEqual(row["last_run_at"], "2026-10-03T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
