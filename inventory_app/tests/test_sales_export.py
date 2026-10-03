import io
import unittest
from datetime import datetime
from unittest.mock import patch

from openpyxl import load_workbook

from tests import test_daily_sales


class SalesExportTest(unittest.TestCase):
    setUp = test_daily_sales.DailySalesTest.setUp
    login = test_daily_sales.DailySalesTest.login
    post = test_daily_sales.DailySalesTest.post
    body = test_daily_sales.DailySalesTest.body
    prepared = test_daily_sales.DailySalesTest.prepared
    quantities = test_daily_sales.DailySalesTest.quantities

    def workbook(self, response):
        self.assertEqual(response.status_code, 200, response.get_json(silent=True))
        self.assertIn('attachment', response.headers['Content-Disposition'])
        book = load_workbook(io.BytesIO(response.data))
        self.addCleanup(book.close)
        return book.active

    def test_draft_numeric_values_text_identifiers_and_no_writes(self):
        self.conn.execute("UPDATE products SET code='0001',name='=1+1' WHERE id=?", (self.ids[0],))
        body = self.body();body['note'] = '=SUM(A1:A2)'
        before = self.quantities()
        with patch.object(self.app.extensions['excel_sync'], 'request') as sync:
            sheet = self.workbook(self.post('/export', body))
        self.assertEqual(sheet.title, '銷售明細')
        self.assertEqual(sheet['A2'].value, datetime(2026, 10, 1))
        self.assertEqual(sheet['B2'].value, '0001')
        self.assertEqual(sheet['C2'].value, '=1+1')
        self.assertEqual(sheet['C2'].data_type, 's')
        self.assertEqual(sheet['H2'].data_type, 's')
        self.assertEqual(sheet['D3'].value, 1.25)
        self.assertEqual(sheet['F2'].value, '草稿／未扣庫存')
        self.assertEqual(sheet.freeze_panes, 'A2')
        self.assertEqual(sheet.auto_filter.ref, 'A1:H3')
        self.assertEqual(self.quantities(), before)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM daily_sales').fetchone()[0], 0)
        sync.assert_not_called()

    def test_posted_and_void_export_preserve_original_product_snapshot(self):
        result = self.post('', self.prepared()).get_json()
        self.conn.execute("UPDATE products SET code='CHANGED',name='改名',unit='件' WHERE id=?", (self.ids[0],))
        before = self.quantities()
        url = f"/api/daily-sales/{result['id']}/excel"
        sheet = self.workbook(self.client.get(url))
        self.assertEqual(sheet['B2'].value, 'A')
        self.assertEqual(sheet['C2'].value, 'A')
        self.assertEqual(sheet['E2'].value, '包')
        self.assertEqual(sheet['F2'].value, '已扣庫存')
        self.assertEqual(self.quantities(), before)
        from uuid import uuid4
        self.post(f"/{result['id']}/void", {'reason': '填錯', 'request_id': str(uuid4())})
        sheet = self.workbook(self.client.get(url))
        self.assertEqual(sheet['F2'].value, '已沖銷')
        self.assertIn('沖銷原因：填錯', sheet['H2'].value)

    def test_draft_export_does_not_require_sufficient_stock(self):
        body = self.body();body['items'][0]['quantity'] = '100'
        sheet = self.workbook(self.post('/export', body))
        self.assertEqual(sheet['D2'].value, 100)

    def test_invalid_drafts_are_rejected(self):
        for quantity in ('', 'NaN', '-2', '0', '1.5'):
            body = self.body();body['items'][0]['quantity'] = quantity
            self.assertEqual(self.post('/export', body).status_code, 400)
        body = self.body();body['items'] = []
        self.assertEqual(self.post('/export', body).status_code, 400)
        body = self.body();body['items'] *= 2
        self.assertEqual(self.post('/export', body).status_code, 400)

    def test_export_auth_csrf_missing_sheet(self):
        self.assertEqual(self.app.test_client().get('/api/daily-sales/1/excel').status_code, 401)
        self.assertEqual(self.client.post('/api/daily-sales/export', json=self.body()).status_code, 403)
        self.assertEqual(self.client.get('/api/daily-sales/999/excel').status_code, 404)
