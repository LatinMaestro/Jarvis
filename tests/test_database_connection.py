import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

from jarvis.database.connection import (
    env_flag,
    open_sqlite_connection,
    prepare_sqlite_db_file,
)


class EnvironmentFlagTests(unittest.TestCase):
    def test_known_true_and_false_values_match_existing_behavior(self):
        for value in ("1", "true", "YES", " on ", "enabled"):
            with self.subTest(value=value), mock.patch.dict(
                os.environ, {"JARVIS_TEST_FLAG": value}
            ):
                self.assertTrue(env_flag("JARVIS_TEST_FLAG"))

        for value in ("0", "false", "off", "anything-else"):
            with self.subTest(value=value), mock.patch.dict(
                os.environ, {"JARVIS_TEST_FLAG": value}
            ):
                self.assertFalse(env_flag("JARVIS_TEST_FLAG"))

    def test_missing_value_uses_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(env_flag("JARVIS_TEST_FLAG", True))
            self.assertFalse(env_flag("JARVIS_TEST_FLAG", False))


class DatabaseFileTests(unittest.TestCase):
    def test_missing_database_is_copied_from_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            seed = root / "seed.db"
            target = root / "nested" / "target.db"
            seed.write_bytes(b"offline-snapshot")

            prepare_sqlite_db_file(str(target), str(seed))

            self.assertEqual(target.read_bytes(), b"offline-snapshot")

    def test_existing_database_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            seed = root / "seed.db"
            target = root / "target.db"
            seed.write_bytes(b"seed")
            target.write_bytes(b"existing")

            prepare_sqlite_db_file(str(target), str(seed))

            self.assertEqual(target.read_bytes(), b"existing")

    def test_connection_uses_existing_sqlite_pragmas(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = pathlib.Path(temp_dir) / "test.db"
            connection, cursor = open_sqlite_connection(str(db_path))
            try:
                self.assertEqual(cursor.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
                self.assertEqual(cursor.execute("PRAGMA synchronous").fetchone()[0], 1)
                self.assertEqual(cursor.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            finally:
                cursor.close()
                connection.close()

            verification = sqlite3.connect(db_path)
            try:
                self.assertEqual(verification.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                verification.close()


if __name__ == "__main__":
    unittest.main()
