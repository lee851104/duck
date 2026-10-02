"""Real PostgreSQL checks. Never uses inventory_app/data.

Set TEST_POSTGRES_URL to an isolated PostgreSQL migrator DSN. Each test creates
and drops its own duck_qa_<uuid> schema. No production schema is modified.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from app.common import Problem
from app.db import connect_db, init_db
from app.inventory import count_stock, receive
from app.products import create_product
from app.shop_catalog import initialize_shop, quote
from app.shop_orders import create_order, transition_order


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_URL'), 'TEST_POSTGRES_URL not configured')
class PostgresIntegrationTest(unittest.TestCase):
    def setUp(self):
        from tools.migrate_postgres import apply_migrations
        self.schema = 'duck_qa_' + uuid4().hex
        self.dsn = os.environ['TEST_POSTGRES_URL']
        self.conn = connect_db(self.dsn, schema=self.schema)
        self.addCleanup(self.cleanup_schema)
        apply_migrations(self.conn)

    def cleanup_schema(self):
        self.conn.rollback()
        self.conn.raw.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.conn.close()

    def product(self, quantity='5'):
        product = create_product(self.conn, {'code': uuid4().hex, 'name': '鴨', 'unit': '包', 'price': '1.25'}, 1)
        batch = self.conn.execute('SELECT id FROM batches WHERE product_id=?', (product['id'],)).fetchone()[0]
        count_stock(self.conn, {'batch_id': batch, 'actual_quantity': quantity,
                    'expected_version': 1, 'request_id': uuid4().hex,
                    'expires_on': '2099-01-01', 'saleable_confirmed': True}, 1)
        return product, batch

    def concurrent(self, callback):
        barrier = Barrier(2)
        def worker(index):
            conn = connect_db(self.dsn, schema=self.schema)
            try:
                barrier.wait(timeout=15)
                try:
                    return callback(conn, index)
                except Problem as exc:
                    return exc.status
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, [0, 1]))

    def test_crud_binding_nulls_and_rollback(self):
        product, _ = self.product()
        self.assertIsNone(product['minimum'])
        self.assertEqual(product['price'], '1.25')
        with self.assertRaises(Problem):
            create_product(self.conn, {'code': product['code'], 'name': 'duplicate', 'unit': '包'}, 1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM products').fetchone()[0], 1)
        text = "? % :name ' ; DROP TABLE products; -- 鴨"
        self.conn.execute('UPDATE products SET name=:name WHERE id=:id', {'name': text, 'id': product['id']})
        self.assertEqual(self.conn.execute('SELECT name FROM products').fetchone()[0], text)

    def test_simultaneous_counts_use_version_and_retry_once(self):
        _, batch = self.product()
        command = {'batch_id': batch, 'actual_quantity': '3', 'expected_version': 2, 'request_id': uuid4().hex}
        results = self.concurrent(lambda conn, index: count_stock(conn, command, 1))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.conn.execute('SELECT version FROM batches WHERE id=?', (batch,)).fetchone()[0], 3)
        stale = self.concurrent(lambda conn, index: count_stock(conn, {**command, 'request_id': uuid4().hex}, 1))
        self.assertEqual(stale, [409, 409])

    def test_distinct_concurrent_counts_reject_one_stale_version(self):
        _, batch = self.product()
        results = self.concurrent(lambda conn, index: count_stock(conn,
            {'batch_id': batch, 'actual_quantity': str(index + 1),
             'expected_version': 2, 'request_id': uuid4().hex}, 1))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn(409, results)
        self.assertEqual(self.conn.execute('SELECT version FROM batches WHERE id=?', (batch,)).fetchone()[0], 3)

    def test_simultaneous_order_confirmation_cannot_overreserve(self):
        product, batch = self.product('1')
        initialize_shop(self.conn, publish_existing=True)
        self.conn.execute("UPDATE metadata SET value=? WHERE key='shop_settings'",
                          (json.dumps({'slots': ['10:00–12:00'], 'enabled': True}),))
        day = date.today()
        selection = {'items': [{'product_id': product['id'], 'quantity': 1}], 'recipes': []}
        quoted = quote(self.conn, selection, day)
        orders = []
        for index in range(2):
            body = {**selection, 'quote_revision': quoted['revision'], 'request_id': uuid4().hex,
                    'name': '客人', 'phone': '0912345678', 'pickup_date': (day + timedelta(days=1)).isoformat(),
                    'pickup_slot': '10:00–12:00'}
            order, _ = create_order(self.conn, body, str(index), str(index), day, 'test-secret')
            orders.append(order)
        results = self.concurrent(lambda conn, index: transition_order(conn, orders[index]['id'], 'confirm', 1, uuid4().hex, day))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn(409, results)
        self.assertEqual(self.conn.execute('SELECT quantity FROM reservations WHERE batch_id=?', (batch,)).fetchone()[0], '1')

    def test_migration_preserves_ids_nulls_roles_and_refuses_nonempty(self):
        from tools.migrate_postgres import apply_migrations, import_sqlite
        apply_migrations(self.conn)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'snapshot.sqlite3'
            local = connect_db(source)
            try:
                init_db(local)
                local.execute("INSERT INTO products(id,code,name,unit,price,created_at,updated_at) VALUES(91,'P','鴨','kg','1.230000','now','now')")
                local.execute("INSERT INTO batches(id,product_id,quantity,cost) VALUES(70,91,NULL,'0.000001')")
                for identity, role in enumerate(('admin', 'owner', 'staff'), 20):
                    local.execute('INSERT INTO staff_accounts(id,email,role,created_at) VALUES(?,?,?,?)', (identity, role+'@example.test', role, 'now'))
                local.execute("INSERT INTO invoice_exports VALUES('z','old','old.xlsx','2026-10-02T12:00:00+08:00')")
                local.execute("INSERT INTO invoice_exports VALUES('a','new','new.xlsx','2026-10-02T12:00:00+08:00')")
            finally:
                local.close()
            counts = import_sqlite(source, self.conn)
            self.assertEqual(counts['products'], 1)
            self.assertEqual(self.conn.execute('SELECT price FROM products WHERE id=91').fetchone()[0], '1.230000')
            self.assertIsNone(self.conn.execute('SELECT quantity FROM batches WHERE id=70').fetchone()[0])
            self.assertEqual([r[0] for r in self.conn.execute('SELECT role FROM staff_accounts ORDER BY id')], ['admin', 'owner', 'staff'])
            self.assertEqual(self.conn.execute("SELECT value FROM metadata WHERE key='latest_invoice_export'").fetchone()[0], 'a')
            with self.assertRaises(ValueError):
                import_sqlite(source, self.conn)
            self.assertGreater(create_product(self.conn, {'code':'NEXT', 'name':'次', 'unit':'包'}, 1)['id'], 91)

    def test_runtime_role_can_read_migration_metadata_but_cannot_mutate_it_or_create_tables(self):
        from tools.migrate_postgres import apply_migrations
        role = 'duck_qa_role_' + uuid4().hex
        self.conn.raw.execute(f'CREATE ROLE "{role}" NOLOGIN')
        try:
            # Managed PostgreSQL migrators are not superusers. Grant membership
            # to the migrator, without making the runtime role inherit anything.
            self.conn.raw.execute(f'GRANT "{role}" TO CURRENT_USER')
            apply_migrations(self.conn, runtime_role=role)
            self.conn.raw.execute(f'SET ROLE "{role}"')
            self.product()
            migrations = self.conn.execute('SELECT version,digest FROM schema_migrations').fetchall()
            self.assertGreater(len(migrations), 0)
            self.assertEqual(len(migrations[0]['digest']), 64)
            with self.assertRaises(sqlite3.Error):
                self.conn.execute(f'CREATE TABLE "{self.schema}".unwanted(id INTEGER)')
            for statement in (
                    "INSERT INTO schema_migrations VALUES('unauthorized.sql','unauthorized')",
                    "UPDATE schema_migrations SET digest='unauthorized'",
                    'DELETE FROM schema_migrations'):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.Error):
                    self.conn.execute(statement)
        finally:
            self.conn.raw.execute('RESET ROLE')
            self.conn.raw.execute(f'DROP OWNED BY "{role}"')
            self.conn.raw.execute(f'REVOKE "{role}" FROM CURRENT_USER')
            self.conn.raw.execute(f'DROP ROLE "{role}"')


if __name__ == '__main__':
    unittest.main()
