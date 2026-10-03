import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

from app.common import Problem
from app.daily_sales import post_sheet
from app.db import connect_db
from app.products import create_product
from tests import test_app


class DailySalesTest(unittest.TestCase):
    login = test_app.AppTest.login

    def setUp(self):
        test_app.AppTest.setUp(self)
        self.login()
        self.headers = {'X-CSRF-Token': self.token}
        self.conn = connect_db(self.app.config['DB_PATH'])
        self.addCleanup(self.conn.close)
        self.ids = []
        for code, unit in [('A', '包'), ('B', '公斤')]:
            p = create_product(self.conn, {'code': code, 'name': code, 'unit': unit}, 1)
            self.ids.append(p['id'])
            self.conn.execute("UPDATE batches SET quantity='3',saleable=1,expires_on='2026-10-02' WHERE product_id=?", (p['id'],))
            self.conn.execute("INSERT INTO batches(product_id,quantity,saleable,expires_on) VALUES(?,'7',1,'2027-01-01')", (p['id'],))

    def post(self, path, body):
        return self.client.post('/api/daily-sales'+path, json=body, headers=self.headers)

    def body(self, items=None):
        return {'sold_on': '2026-10-01', 'note': '晚班', 'items': items or [
            {'product_id': self.ids[0], 'quantity': '5'}, {'product_id': self.ids[1], 'quantity': '1.25'}]}

    def prepared(self, body=None):
        body = body or self.body()
        preview = self.post('/preview', body)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        return {**body, 'revision': preview.get_json()['revision'], 'request_id': str(uuid4())}

    def quantities(self):
        return [r[0] for r in self.conn.execute('SELECT quantity FROM batches ORDER BY id')]

    def test_atomic_fefo_decimal_and_retry(self):
        body = self.prepared()
        response = self.post('', body)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.quantities(), ['0', '5', '1.75', '7'])
        self.assertEqual(self.post('', body).get_json(), response.get_json())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM movements WHERE kind='issue'").fetchone()[0], 3)
        self.assertEqual(self.post('/preview', self.body()).status_code, 409)
        self.assertEqual(self.client.get('/api/daily-sales').get_json()['total'], 1)

    def test_insufficient_second_item_no_partial_writes(self):
        body = self.body();body['items'][1]['quantity'] = '11'
        response = self.post('', {**body, 'request_id': str(uuid4()), 'revision': 'stale'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.quantities(), ['3', '7', '3', '7'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM daily_sales').fetchone()[0], 0)

    def test_changed_inventory_requires_new_preview(self):
        body = self.prepared()
        self.conn.execute('UPDATE batches SET version=version+1 WHERE product_id=?', (self.ids[1],))
        self.assertEqual(self.post('', body).status_code, 409)
        self.assertEqual(self.quantities(), ['3', '7', '3', '7'])

    def test_invalid_inputs(self):
        for value in ['0', '-1', 'NaN', '0.5', '', None]:
            body = self.body();body['items'][0]['quantity'] = value
            self.assertEqual(self.post('/preview', body).status_code, 400)
        for items in [[], [None], [{'product_id': True, 'quantity': 1}], self.body()['items'] * 2]:
            self.assertEqual(self.post('/preview', {**self.body(), 'items': items}).status_code, 400)
        self.assertEqual(self.post('/preview', {**self.body(), 'sold_on': '2026-10-02'}).status_code, 400)

    def test_expiry_saleable_unknown_and_received_date(self):
        pid = self.ids[0]
        self.conn.execute("UPDATE batches SET expires_on='2026-09-30' WHERE product_id=?", (pid,))
        body = self.body([{'product_id': pid, 'quantity': '1'}])
        self.assertEqual(self.post('/preview', body).status_code, 409)
        self.conn.execute('UPDATE batches SET expires_on=NULL,saleable=0 WHERE product_id=?', (pid,))
        self.assertEqual(self.post('/preview', body).status_code, 409)
        self.conn.execute('UPDATE batches SET saleable=1 WHERE product_id=?', (pid,))
        self.assertEqual(self.post('/preview', body).status_code, 200)
        self.conn.execute("UPDATE batches SET received_on='2026-10-02' WHERE product_id=?", (pid,))
        self.assertEqual(self.post('/preview', body).status_code, 409)
        self.conn.execute('UPDATE batches SET received_on=NULL,quantity=NULL WHERE product_id=?', (pid,))
        self.assertEqual(self.post('/preview', body).status_code, 409)

    def test_void_whole_sheet_and_refill(self):
        result = self.post('', self.prepared()).get_json();sid = result['id']
        movement = result['items'][0]['allocations'][0]['movement_id']
        response = self.client.post('/api/reversals', json={'movement_id': movement, 'reason': '錯填', 'request_id': str(uuid4())}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        command = {'reason': '數量填錯', 'request_id': str(uuid4())}
        result = self.post(f'/{sid}/void', command)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.post(f'/{sid}/void', command).get_json(), result.get_json())
        self.assertEqual(self.quantities(), ['3', '7', '3', '7'])
        self.assertEqual(self.post('', self.prepared()).status_code, 200)

    def test_count_after_sale_blocks_entire_void(self):
        result = self.post('', self.prepared()).get_json()
        batch = result['items'][1]['allocations'][0]['batch_id']
        version = self.conn.execute('SELECT version FROM batches WHERE id=?', (batch,)).fetchone()[0]
        self.client.post('/api/counts', json={'batch_id': batch, 'expected_version': version,
            'actual_quantity': '2', 'request_id': str(uuid4())}, headers=self.headers)
        before = self.quantities()
        self.assertEqual(self.post(f"/{result['id']}/void", {'reason': '錯填', 'request_id': str(uuid4())}).status_code, 409)
        self.assertEqual(self.quantities(), before)

    def test_concurrent_submissions_only_one_sheet(self):
        body = self.prepared()
        def submit(command):
            conn = connect_db(self.app.config['DB_PATH'])
            try:
                return post_sheet(conn, command, 1, date(2026, 10, 1))['id']
            except Problem:
                return None
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, [body, {**body, 'request_id': str(uuid4())}]))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.quantities(), ['0', '5', '1.75', '7'])

    def test_existing_customer_reservations_are_not_consumed(self):
        self.conn.execute('''INSERT INTO customer_orders VALUES(
            'old','old','token','client','old-request','hash','confirmed','test','00000000',
            '2099-01-01','10:00–12:00','2099-01-01T12:00:00+08:00','0','{}','2026-10-01','2026-10-01')''')
        bid = self.conn.execute('SELECT id FROM batches WHERE product_id=? ORDER BY id LIMIT 1', (self.ids[0],)).fetchone()[0]
        self.conn.execute("INSERT INTO reservations VALUES('old',?,'3')", (bid,))
        result = self.post('', self.prepared()).get_json()
        self.assertIn('id', result)
        self.assertEqual(self.quantities(), ['3', '2', '1.75', '7'])

    def test_product_list_reports_server_today(self):
        # 分頁開著過夜時，前端靠這個日期判斷草稿日期是否過期。
        self.assertEqual(self.client.get('/api/daily-sales/products').get_json()['today'], '2026-10-01')

    def test_backfill_after_count_requires_confirmation(self):
        pid = self.ids[0]
        bid, version = self.conn.execute('SELECT id,version FROM batches WHERE product_id=? ORDER BY id LIMIT 1', (pid,)).fetchone()
        response = self.client.post('/api/counts', json={'batch_id': bid, 'expected_version': version,
            'actual_quantity': '2', 'request_id': str(uuid4())}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = {**self.body([{'product_id': pid, 'quantity': '1'}]), 'sold_on': '2026-09-30'}
        # 盤點時間固定下來，不受執行測試當天影響；銷售日之前的盤點不提醒。
        self.conn.execute("UPDATE movements SET created_at='2026-09-29T20:00:00+08:00' WHERE kind='count'")
        self.assertEqual(self.post('/preview', body).get_json()['warnings'], [])
        self.conn.execute("UPDATE movements SET created_at='2026-10-01T09:00:00+08:00' WHERE kind='count'")
        plan = self.post('/preview', body).get_json()
        self.assertEqual([w['kind'] for w in plan['warnings']], ['counted'])
        self.assertIn('10/01 09:00', plan['warnings'][0]['message'])
        command = {**body, 'revision': plan['revision'], 'request_id': str(uuid4())}
        before = self.quantities()
        refused = self.post('', command)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.get_json()['error']['code'], 'sale_warnings')
        self.assertEqual(self.quantities(), before)
        self.assertEqual(self.post('', {**command, 'confirm_warnings': True}).status_code, 200)
        self.assertEqual(self.quantities(), ['1', '7', '3', '7'])
        # 當天的單不看盤點時間：早上盤點、晚上結帳是正常流程。
        self.assertEqual(self.post('/preview', self.body()).get_json()['warnings'], [])

    def test_backfill_after_later_sheet_uses_later_batches(self):
        pid = self.ids[0]
        old, new = [r[0] for r in self.conn.execute('SELECT id FROM batches WHERE product_id=? ORDER BY id', (pid,))]
        self.conn.execute("UPDATE batches SET received_on='2026-09-20' WHERE id=?", (old,))
        self.conn.execute("UPDATE batches SET received_on='2026-10-01' WHERE id=?", (new,))
        # 10/1 的單先送出，依效期扣光舊批次；回頭補登 9/30 時，舊批次已經不夠扣。
        self.assertEqual(self.post('', self.prepared(self.body([{'product_id': pid, 'quantity': '3'}]))).status_code, 200)
        body = {**self.body([{'product_id': pid, 'quantity': '2'}]), 'sold_on': '2026-09-30'}
        plan = self.post('/preview', body).get_json()
        self.assertEqual([w['kind'] for w in plan['warnings']], ['later_stock'])
        self.assertEqual([(a['batch_id'], a['quantity'], a.get('later')) for a in plan['items'][0]['allocations']],
                         [(new, '2', True)])
        command = {**body, 'revision': plan['revision'], 'request_id': str(uuid4())}
        self.assertEqual(self.post('', command).status_code, 409)
        self.assertEqual(self.post('', {**command, 'confirm_warnings': True}).status_code, 200)
        self.assertEqual(self.quantities()[:2], ['0', '5'])
        refused = self.post('/preview', {**self.body([{'product_id': pid, 'quantity': '6'}]), 'sold_on': '2026-09-29'})
        self.assertEqual(refused.status_code, 409)
        self.assertIn('之後進貨 5', refused.get_json()['error']['message'])

    def test_same_day_manual_sale_requires_confirmation_until_reversed(self):
        pid = self.ids[0]
        bid, version = self.conn.execute('SELECT id,version FROM batches WHERE product_id=? ORDER BY id DESC LIMIT 1', (pid,)).fetchone()
        issued = self.client.post('/api/issues', json={'product_id': pid, 'reason': '銷售', 'request_id': str(uuid4()),
            'allocations': [{'batch_id': bid, 'quantity': '2', 'expected_version': version}]}, headers=self.headers)
        self.assertEqual(issued.status_code, 200, issued.get_json())
        self.conn.execute("UPDATE movements SET created_at='2026-10-01T11:00:00+08:00' WHERE kind='issue'")
        plan = self.post('/preview', self.body()).get_json()
        self.assertEqual([(w['product_id'], w['kind']) for w in plan['warnings']], [(pid, 'manual_sale')])
        self.assertIn('記錄 2 包', plan['warnings'][0]['message'])
        command = {**self.body(), 'revision': plan['revision'], 'request_id': str(uuid4())}
        self.assertEqual(self.post('', command).get_json()['error']['code'], 'sale_warnings')
        reversal = self.client.post('/api/reversals', json={'movement_id': issued.get_json()['movement_ids'][0],
            'reason': '改用每日銷售單', 'request_id': str(uuid4())}, headers=self.headers)
        self.assertEqual(reversal.status_code, 200, reversal.get_json())
        self.assertEqual(self.post('/preview', self.body()).get_json()['warnings'], [])

    def test_auth_and_customer_ordering_disabled(self):
        self.assertEqual(self.app.test_client().get('/api/daily-sales').status_code, 401)
        self.assertEqual(self.client.post('/api/daily-sales', json=self.body()).status_code, 403)
        self.assertEqual(self.app.test_client().get('/api/shop/catalog').status_code, 410)
        self.assertEqual(self.client.post('/api/shop/orders', json={}, headers=self.headers).status_code, 410)
        self.assertEqual(self.client.get('/shop').location, '/#daily-sales')
        self.assertEqual(self.client.post('/api/shop-admin/settings', json={'enabled': True}, headers=self.headers).status_code, 410)
