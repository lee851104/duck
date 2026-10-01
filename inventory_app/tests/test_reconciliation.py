import json
import sqlite3
import unittest
from contextlib import closing

from app.db import connect_db, init_db
from tests import test_app


class ReconciliationTest(unittest.TestCase):
    login = test_app.AppTest.login

    def setUp(self):
        test_app.AppTest.setUp(self)
        self.login()
        self.headers = {'X-CSRF-Token': self.token}
        self.product = self.client.post('/api/products', json={
            'code': 'T1', 'name': '六入鮮乳', 'unit': '手', 'price': '120'},
            headers=self.headers).get_json()
        with closing(connect_db(self.app.config['DB_PATH'])) as conn:
            conn.execute("INSERT INTO catalog_cards(source,name,specification,original_price) "
                         "VALUES('milk!A1','鮮乳整箱','24入／箱','450')")

    def test_independent_card_is_not_pending_and_can_be_revised(self):
        result = self.client.post('/api/mappings/catalog/1', json={
            'product_id': None, 'independent': True, 'pricing_mode': 'fixed'}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get('/api/mappings/catalog?pending=1').get_json()['total'], 0)
        card = self.client.get('/api/catalog?q=整箱').get_json()['items'][0]
        self.assertEqual(card['status'], 'independent')
        self.assertEqual(card['price'], '450')
        self.assertFalse(card['linked'])
        result = self.client.post('/api/mappings/catalog/1', json={
            'product_id': self.product['id'], 'independent': True, 'pricing_mode': 'fixed'},
            headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.client.get('/api/mappings/catalog').get_json()['items'][0]['independent'])

    def test_old_database_migration_keeps_source_rows(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.execute('CREATE TABLE catalog_cards(id INTEGER PRIMARY KEY,source TEXT,name TEXT)')
        conn.execute("INSERT INTO catalog_cards VALUES(1,'old','舊商品')")
        init_db(conn)
        init_db(conn)
        self.assertEqual(conn.execute('SELECT name,independent FROM catalog_cards').fetchone(), ('舊商品', 0))

    def test_plan_is_atomic_idempotent_and_keeps_stock_unknown(self):
        from tools.reconcile_sources import apply_plan
        with closing(connect_db(self.app.config['DB_PATH'])) as conn:
            before_batches = [dict(r) for r in conn.execute('SELECT * FROM batches')]
            plan = {'id': 'unit-test', 'actions': [
                {'table': 'catalog_cards', 'id': 1, 'before': {'product_id': None},
                 'after': {'independent': 1}, 'reason': '不同包裝，保留獨立來源'},
                {'table': 'products', 'id': self.product['id'], 'before': {'price': None},
                 'after': {'price': '100'}, 'reason': '只補空白價'}]}
            with self.assertRaises(ValueError):
                apply_plan(conn, plan)
            self.assertEqual(conn.execute('SELECT independent FROM catalog_cards').fetchone()[0], 0)
            plan['actions'].pop()
            first = apply_plan(conn, plan)
            conn.execute("UPDATE catalog_cards SET independent=0")
            repeated = apply_plan(conn, plan)
            self.assertEqual(first, repeated)
            self.assertEqual(conn.execute('SELECT independent FROM catalog_cards').fetchone()[0], 0)
            self.assertEqual([dict(r) for r in conn.execute('SELECT * FROM batches')], before_batches)
            self.assertEqual(conn.execute('SELECT price FROM products').fetchone()[0], '120')

    def test_filled_price_has_source_history_and_does_not_replace_existing_price(self):
        from tools.reconcile_sources import apply_plan
        with closing(connect_db(self.app.config['DB_PATH'])) as conn:
            conn.execute('UPDATE products SET price=NULL WHERE id=?', (self.product['id'],))
            plan = {'id': 'price-test', 'actions': [{
                'table': 'products', 'id': self.product['id'],
                'before': {'price': None, 'version': self.product['version']},
                'after': {'price': '115'}, 'reason': '依原價目表 A!E11 補價，可修改'}]}
            apply_plan(conn, plan)
            row = conn.execute('SELECT price,version FROM products').fetchone()
            self.assertEqual(tuple(row), ('115', self.product['version']+1))
            movement = conn.execute("SELECT * FROM movements WHERE kind='price'").fetchone()
            self.assertIn('A!E11', movement['reason'])
            self.assertIsNone(movement['before_value'])
            self.assertEqual(movement['after_value'], '115')
            self.assertTrue(json.loads(conn.execute("SELECT value FROM metadata WHERE key='reconciliation:price-test'").fetchone()[0]))
