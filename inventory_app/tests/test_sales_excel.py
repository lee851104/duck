import io
import unittest
from unittest.mock import patch
from uuid import uuid4

from openpyxl import Workbook

from app.products import create_product
from app.db import connect_db
from tests import test_app


class SalesExcelTest(unittest.TestCase):
    login = test_app.AppTest.login

    def setUp(self):
        test_app.AppTest.setUp(self)
        self.login()
        self.headers = {'X-CSRF-Token': self.token}
        self.conn = connect_db(self.app.config['DB_PATH'])
        self.addCleanup(self.conn.close)
        self.product = create_product(self.conn, {'code': '001', 'name': '雞腿', 'unit': '包'}, 1)

    def upload(self, rows, sheet='銷售明細'):
        book = Workbook()
        book.active.title = sheet
        for row in rows:
            book.active.append(row)
        stream = io.BytesIO()
        book.save(stream)
        stream.seek(0)
        return self.client.post('/api/daily-sales/excel', headers=self.headers,
                                data={'file': (stream, '銷售.xlsx')})

    def post_sheet(self, quantity):
        self.conn.execute("UPDATE batches SET quantity='10',saleable=1,expires_on='2027-01-01' WHERE product_id=?",
                          (self.product['id'],))
        body = {'sold_on': '2026-10-01', 'note': '', 'items': [{'product_id': self.product['id'], 'quantity': quantity}]}
        plan = self.client.post('/api/daily-sales/preview', json=body, headers=self.headers).get_json()
        response = self.client.post('/api/daily-sales', headers=self.headers,
                                    json={**body, 'revision': plan['revision'], 'request_id': str(uuid4())})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['id']

    def test_old_line_export_skips_cancelled_and_deducted_rows(self):
        sid = self.post_sheet('1')
        response = self.upload([['類型', '商品', '數量', '單位', '店內品號', '狀態', '訂單編號', '已扣庫存銷售單'],
                                ['新訂單', '雞腿', 2, '包', '001', '已完成', 1, ''],
                                ['取消', '雞腿', 4, '包', '001', '已完成', 2, ''],
                                ['新訂單', '雞腿', 3, '包', '001', '已完成', 3, f'#{sid}'],
                                ['修改', '雞腿', 1, '包', '001', '待處理', 4, ''],
                                ['新訂單', '雞腿', 5, '包', '001', '已完成', 5, '#999'],
                                ['新訂單', '（沒有辨識出品項）', None, '', '', '已完成', 6, '']], sheet='訂單明細')
        data = response.get_json()
        self.assertEqual(response.status_code, 200, data)
        self.assertEqual(sorted(s['kind'] for s in data['skipped']), ['cancel', 'linked'])
        items = data['orders'][0]['items']
        self.assertEqual([i['quantity'] for i in items], ['2', '1', '5'])
        self.assertEqual(items[0]['warning'], '')
        self.assertIn('修改單', items[1]['warning'])
        self.assertIn('待處理', items[1]['warning'])
        self.assertIn('#999', items[2]['warning'])

    def test_own_export_is_skipped_until_the_sheet_is_voided(self):
        sid = self.post_sheet('2')
        exported = self.client.get(f'/api/daily-sales/{sid}/excel').data

        def preview(sold_on='2026-10-01'):
            response = self.client.post('/api/daily-sales/excel', headers=self.headers,
                                        data={'file': (io.BytesIO(exported), '每日銷售.xlsx'), 'sold_on': sold_on})
            self.assertEqual(response.status_code, 200, response.get_json())
            return response.get_json()

        data = preview()
        self.assertEqual((data['orders'], [s['kind'] for s in data['skipped']]), ([], ['linked']))
        void = self.client.post(f'/api/daily-sales/{sid}/void', headers=self.headers,
                                json={'reason': '重填', 'request_id': str(uuid4())})
        self.assertEqual(void.status_code, 200, void.get_json())
        item = preview()['orders'][0]['items'][0]
        self.assertEqual((item['product']['id'], item['quantity'], item['warning']), (self.product['id'], '2', ''))
        self.assertIn('2026-09-30', preview('2026-09-30')['orders'][0]['items'][0]['warning'])

    def test_standalone_preview_does_not_mutate_or_sync(self):
        before = self.conn.execute('SELECT COUNT(*) FROM movements').fetchone()[0]
        with patch.object(self.app.extensions['excel_sync'], 'request') as sync:
            response = self.upload([['品號', '商品', '數量', '單位'], ['001', '雞腿', 2, '包']])
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertTrue(data['standalone'])
        item = data['orders'][0]['items'][0]
        self.assertEqual(item['product']['id'], self.product['id'])
        self.assertEqual(item['quantity'], '2')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM line_orders').fetchone()[0], 0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM movements').fetchone()[0], before)
        sync.assert_not_called()

    def test_name_match_unknown_code_and_invalid_quantity_require_review(self):
        response = self.upload([['商品', '品號', '數量'], ['雞腿', None, 1.5],
                                ['雞腿', 'missing', 2], ['不存在', None, -3]])
        items = response.get_json()['orders'][0]['items']
        self.assertEqual(items[0]['product']['id'], self.product['id'])
        self.assertEqual(items[0]['quantity'], '1.5')
        self.assertIsNone(items[1]['product'])
        self.assertIn('找不到品號', items[1]['warning'])
        self.assertIsNone(items[2]['quantity'])

    def test_legacy_workbook_needs_no_line_database(self):
        response = self.upload([['訂單編號', '店內品號', '商品', '數量'],
                                [987, '001', '雞腿', 3]], sheet='訂單明細')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['orders'][0]['items'][0]['quantity'], '3')

    def test_invalid_headers_and_empty_data(self):
        self.assertEqual(self.upload([['價格'], [100]]).status_code, 400)
        self.assertEqual(self.upload([['品號', '數量']]).status_code, 400)

    def test_line_module_disabled_and_excel_requires_auth_csrf(self):
        self.assertEqual(self.client.get('/api/line-orders').status_code, 404)
        self.assertEqual(self.client.post('/api/line-orders/import', headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get('/api/daily-sales/line-orders').status_code, 404)
        self.assertEqual(self.app.test_client().post('/api/daily-sales/excel').status_code, 401)
        self.assertEqual(self.client.post('/api/daily-sales/excel').status_code, 403)
        self.assertNotIn(b'data-nav="line-orders"', self.client.get('/').data)
