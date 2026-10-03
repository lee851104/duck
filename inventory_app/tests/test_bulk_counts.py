import unittest
from uuid import uuid4

from tests import test_app
from app.db import connect_db
from app.products import create_product


class BulkCountsTest(unittest.TestCase):
    login = test_app.AppTest.login

    def setUp(self):
        test_app.AppTest.setUp(self)
        self.login()
        self.headers = {'X-CSRF-Token': self.token}
        self.conn = connect_db(self.app.config['DB_PATH'])
        self.addCleanup(self.conn.close)
        self.ids = []
        for code in ['ONE', 'TWO']:
            product = create_product(self.conn, {'code': code, 'name': code, 'unit': '包'}, 1)
            batch = self.conn.execute('SELECT id FROM batches WHERE product_id=?', (product['id'],)).fetchone()
            self.ids.append(batch[0])

    def payload(self):
        return {'request_id': str(uuid4()), 'items': [
            {'batch_id': bid, 'expected_version': 1, 'actual_quantity': str(index)}
            for index, bid in enumerate(self.ids)]}

    def post(self, body):
        return self.client.post('/api/counts/bulk', json=body, headers=self.headers)

    def test_zero_and_multiple_rows_saved_once(self):
        body = self.payload()
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(len(response.get_json()['results']), 2)
        self.assertEqual(self.post(body).get_json(), response.get_json())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM movements WHERE kind='count'").fetchone()[0], 2)
        rows = self.conn.execute('SELECT quantity,version,expires_on,saleable FROM batches ORDER BY id').fetchall()
        self.assertEqual([(r['quantity'], r['version']) for r in rows], [('0', 2), ('1', 2)])
        self.assertTrue(all(r['expires_on'] is None for r in rows))

    def test_conflict_rolls_back_every_row(self):
        body = self.payload()
        self.conn.execute('UPDATE batches SET version=2 WHERE id=?', (self.ids[1],))
        response = self.post(body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error']['fields']['batch_id'], self.ids[1])
        self.assertIsNone(self.conn.execute('SELECT quantity FROM batches WHERE id=?', (self.ids[0],)).fetchone()[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM movements WHERE kind='count'").fetchone()[0], 0)

    def test_reject_invalid_and_duplicate_rows(self):
        for bad in ['', None, -1, 'NaN', 0.5]:
            body = self.payload()
            body['items'][1]['actual_quantity'] = bad
            self.assertEqual(self.post(body).status_code, 400, bad)
        body = self.payload()
        body['items'][1] = body['items'][0]
        self.assertEqual(self.post(body).status_code, 400)
        for items in [[], {}, [None], self.payload()['items'] * 101]:
            self.assertEqual(self.post({'request_id': str(uuid4()), 'items': items}).status_code, 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM movements WHERE kind='count'").fetchone()[0], 0)

    def product(self, batch_id):
        pid = self.conn.execute('SELECT product_id FROM batches WHERE id=?', (batch_id,)).fetchone()[0]
        return self.client.get(f'/api/products/{pid}').get_json()

    def test_counted_unconfirmed_stock_is_not_out_of_stock(self):
        body = self.payload()
        body['items'][1]['actual_quantity'] = '6'
        self.assertEqual(self.post(body).status_code, 200)
        product = self.product(self.ids[1])
        self.assertEqual((product['status'], product['quantity'], product['unconfirmed_quantity']),
                         ('unconfirmed', '0', '6'))
        codes = lambda status: [p['code'] for p in self.client.get(f'/api/products?status={status}').get_json()['items']]
        self.assertEqual(codes('restock'), ['ONE'])  # 盤點為 0 才是真的缺貨
        self.assertEqual(codes('unconfirmed'), ['TWO'])
        dashboard = self.client.get('/api/dashboard').get_json()
        self.assertEqual(dashboard['out_of_stock_products'], 1)
        self.assertIn(('TWO', 'unconfirmed', '6'), [(a['name'], a['status'], a['quantity']) for a in dashboard['alerts']['items']])

    def test_stocktake_can_confirm_saleable(self):
        body = self.payload()
        body['items'][1].update(actual_quantity='6', saleable_confirmed=True)
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.get_json())
        product = self.product(self.ids[1])
        self.assertEqual((product['status'], product['quantity']), ('normal', '6'))
        reason = self.conn.execute("SELECT reason FROM movements WHERE batch_id=? AND kind='count'", (self.ids[1],)).fetchone()[0]
        self.assertIn('確認可售', reason)
        available = {p['code']: p['available'] for p in self.client.get('/api/daily-sales/products').get_json()['items']}
        self.assertEqual(available['TWO'], '6')

    def test_stocktake_only_confirms_saleable(self):
        for value in (False, 'true', 1, None):
            body = self.payload()
            body['items'][1]['saleable_confirmed'] = value
            self.assertEqual(self.post(body).status_code, 400, value)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM movements WHERE kind='count'").fetchone()[0], 0)

    def test_authentication_and_csrf_required(self):
        self.assertEqual(self.app.test_client().post('/api/counts/bulk', json=self.payload()).status_code, 401)
        self.assertEqual(self.client.post('/api/counts/bulk', json=self.payload()).status_code, 403)
