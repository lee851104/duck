import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.db import connect_db, init_db


class MigrationContractTest(unittest.TestCase):
    def migration(self):
        self.assertIsNotNone(importlib.util.find_spec('tools.migrate_postgres'),
                             'An explicit offline migration tool is required')
        return importlib.import_module('tools.migrate_postgres')

    def test_snapshot_is_readonly_source_and_preserves_null_and_text(self):
        module = self.migration()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.sqlite3'
            conn = connect_db(path)
            init_db(conn)
            conn.execute("INSERT INTO products(id,code,name,unit,price,created_at,updated_at) VALUES(12,'A','鴨','kg','0.000010','now','now')")
            conn.execute('INSERT INTO batches(product_id,quantity) VALUES(12,NULL)')
            with module.sqlite_snapshot(path) as snapshot:
                conn.execute("UPDATE products SET price='99'")
                self.assertEqual(snapshot.execute('SELECT price FROM products').fetchone()[0], '0.000010')
                self.assertIsNone(snapshot.execute('SELECT quantity FROM batches').fetchone()[0])
                with self.assertRaises(sqlite3.OperationalError):
                    snapshot.execute('DELETE FROM products')
            conn.close()

    def test_missing_source_never_creates_empty_file(self):
        module = self.migration()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.sqlite3'
            with self.assertRaises(FileNotFoundError):
                with module.sqlite_snapshot(path):
                    pass
            self.assertFalse(path.exists())

    def test_local_initializer_explicitly_refuses_postgres(self):
        class CloudConnection:
            dialect = 'postgres'
        with self.assertRaisesRegex(RuntimeError, 'explicit'):
            init_db(CloudConnection())

    def test_public_service_roles_cannot_be_granted_runtime_access(self):
        migration = self.migration()
        conn = SimpleNamespace(dialect='postgres', schema='duck', raw=None)
        for role in ('anon', 'authenticated', 'service_role', 'postgres'):
            with self.subTest(role=role), self.assertRaises(ValueError):
                migration.apply_migrations(conn, runtime_role=role)


if __name__ == '__main__':
    unittest.main()
