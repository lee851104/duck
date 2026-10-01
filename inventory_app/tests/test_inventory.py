import tempfile
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.common import Problem
from app.db import connect_db, init_db
from app.products import create_product
from app.inventory import receive, issue, count_stock, reverse_movement, return_stock
from app.dashboard import list_products, get_dashboard

TODAY = date(2026, 10, 1)


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = connect_db(Path(self.tmp.name)/'test.db')
        self.addCleanup(self.conn.close)
        init_db(self.conn)
        self.product = create_product(self.conn, {'code': 'P1', 'name': '芋頭貢丸',
                                     'unit': '包', 'price': '150', 'minimum': '3'}, 1)
        self.pid = self.product['id']
        # New products start uncounted; establish the opening balance explicitly.
        opening = self.conn.execute('SELECT * FROM batches').fetchone()
        count_stock(self.conn, {'batch_id': opening['id'], 'actual_quantity': '0',
                    'expected_version': 1, 'request_id': str(uuid4())}, 1)

    def receipt(self, quantity='2', expires='2027-01-18', **extra):
        return receive(self.conn, {'product_id': self.pid, 'quantity': quantity,
                       'cost': '125', 'received_on': '2026-10-01',
                       'expires_on': expires, 'request_id': str(uuid4()), **extra}, 1)

    def send(self, allocations, **extra):
        return issue(self.conn, {'product_id': self.pid, 'allocations': allocations,
                     'reason': '銷售', 'request_id': str(uuid4()), **extra}, 1, TODAY)

    def allocation(self, batch, quantity):
        return {'batch_id': batch['batch_id'], 'quantity': quantity, 'expected_version': 1}

    def test_batches_aggregate_and_cross_batch_issue(self):
        a, b = self.receipt(), self.receipt('7', '2027-02-24')
        self.assertEqual(list_products(self.conn, '', '', 1, 10, TODAY)['items'][0]['quantity'], '9')
        self.send([self.allocation(a, '2'), self.allocation(b, '1')])
        self.assertEqual(list_products(self.conn, '', '', 1, 10, TODAY)['items'][0]['quantity'], '6')

    def test_shortage_rolls_back_entire_issue(self):
        a, b = self.receipt(), self.receipt('1')
        with self.assertRaises(Problem):
            self.send([self.allocation(a, '1'), self.allocation(b, '2')])
        self.assertEqual(self.conn.execute('SELECT quantity FROM batches WHERE id=?', (a['batch_id'],)).fetchone()[0], '2')

    def test_duplicate_request_exactly_once(self):
        a = self.receipt()
        key = str(uuid4())
        first = self.send([self.allocation(a, '1')], request_id=key)
        self.assertEqual(self.send([self.allocation(a, '1')], request_id=key), first)
        self.assertEqual(self.conn.execute('SELECT quantity FROM batches WHERE id=?', (a['batch_id'],)).fetchone()[0], '1')
        with self.assertRaises(Problem):
            self.send([self.allocation(a, '2')], request_id=key)

    def test_stale_version_cannot_deduct_twice(self):
        a = self.receipt()
        self.send([self.allocation(a, '1')])
        with self.assertRaises(Problem):
            self.send([self.allocation(a, '1')])

    def test_expired_sale_rejected_disposal_allowed(self):
        a = self.receipt(expires='2026-09-30')
        with self.assertRaises(Problem):
            self.send([self.allocation(a, '1')])
        self.send([self.allocation(a, '1')], reason='報廢')

    def test_unknown_expiry_needs_saleable_confirmation(self):
        a = self.receipt(expires=None, unknown_expiry=True)
        with self.assertRaises(Problem):
            self.send([self.allocation(a, '1')])

    def test_uncounted_product_not_zero(self):
        p = create_product(self.conn, {'code': 'P2', 'name': '未盤點', 'unit': '瓶'}, 1)
        d = get_dashboard(self.conn, TODAY, 1, 6)
        self.assertEqual(d['uncounted_products'], 1)
        self.assertEqual(d['out_of_stock_products'], 1)
        row = list_products(self.conn, '未盤點', '', 1, 10, TODAY)['items'][0]
        self.assertIsNone(row['quantity'])

    def test_expiry_boundaries(self):
        self.receipt(expires='2026-10-01')
        self.receipt(expires='2026-10-31')
        self.receipt(expires='2026-11-01')
        self.receipt(expires='2026-09-30')
        d = get_dashboard(self.conn, TODAY, 1, 6)
        self.assertEqual(d['expiring_batches'], 2)
        self.assertEqual(d['expired_batches'], 1)
        self.assertEqual(d['alerts']['items'][0]['status'], 'expired')

    def test_fractional_pack_rejected(self):
        with self.assertRaises(Problem):
            self.receipt('0.5')

    def test_nonfinite_rejected(self):
        for quantity in ['NaN', 'Infinity', '-2']:
            with self.assertRaises(Problem):
                self.receipt(quantity)

    def test_customer_return_not_saleable(self):
        result = return_stock(self.conn, {'product_id': self.pid, 'quantity': '1',
                   'cost': None, 'expires_on': '2027-01-01', 'received_on': '2026-10-01',
                   'request_id': str(uuid4())}, 1)
        with self.assertRaises(Problem):
            self.send([self.allocation(result, '1')])

    def test_reversal_preserves_history(self):
        a = self.receipt()
        out = self.send([self.allocation(a, '1')])
        reverse_movement(self.conn, out['movement_ids'][0], '登記錯誤', str(uuid4()), 1)
        self.assertEqual(self.conn.execute('SELECT quantity FROM batches WHERE id=?', (a['batch_id'],)).fetchone()[0], '2')
        with self.assertRaises(Problem):
            reverse_movement(self.conn, out['movement_ids'][0], '再撤銷', str(uuid4()), 1)

    def test_reversing_consumed_receipt_rejected(self):
        a = self.receipt()
        self.send([self.allocation(a, '1')])
        with self.assertRaises(Problem):
            reverse_movement(self.conn, a['movement_ids'][0], '錯誤', str(uuid4()), 1)

    def test_expected_total_mismatch_rolls_back(self):
        a = self.receipt()
        with self.assertRaises(Problem):
            self.send([self.allocation(a, '2')], expected_total='3')
        self.assertEqual(self.conn.execute('SELECT quantity FROM batches WHERE id=?',(a['batch_id'],)).fetchone()[0],'2')
