"""Remote database reads must not grow one query per batch."""
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.dashboard import products_with_stock
from app.db import connect_db, init_db
from app.shop_catalog import product_map


class ReservationQueriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = connect_db(Path(self.tmp.name) / 'test.sqlite3')
        self.addCleanup(self.conn.close)
        init_db(self.conn)
        self.conn.execute("INSERT INTO products(id,code,name,unit,price,created_at,updated_at) VALUES(1,'P','鴨','包','3','now','now')")
        for identity in range(1, 11):
            self.conn.execute("INSERT INTO batches(id,product_id,quantity,expires_on,saleable) VALUES(?,1,'5','2099-01-01',1)", (identity,))
        for identity, status, until, quantity in [('a','confirmed','2099-01-01','1.000001'),
                ('b','ready','2099-01-01','2.999999'), ('c','pending','2099-01-01','5'),
                ('d','cancelled','2099-01-01','5'), ('e','confirmed','2000-01-01','5')]:
            self.conn.execute('INSERT INTO customer_orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,identity,identity,'client',identity,'hash',status,'name','phone','2099-01-01','slot',until,'3','{}','now','now'))
            self.conn.execute('INSERT INTO reservations VALUES(?,1,?)', (identity, quantity))
        self.conn.execute('INSERT INTO shop_products VALUES(1,1)')
        self.statements = []
        self.conn.set_trace_callback(self.statements.append)

    def reservation_reads(self):
        return sum('from reservations' in statement.lower() for statement in self.statements)

    def test_dashboard_uses_one_reservation_query_and_preserves_active_decimal_total(self):
        product = products_with_stock(self.conn, date(2026,10,1))[0]
        self.assertEqual(product['reserved_quantity'], '4')
        self.assertEqual(product['quantity'], '46')
        self.assertEqual(product['batches'][0]['reserved_quantity'], '4')
        self.assertEqual(product['batches'][1]['reserved_quantity'], '0')
        self.assertLessEqual(self.reservation_reads(), 1)

    def test_public_catalog_reuses_the_same_batch_reservation_snapshot(self):
        product = product_map(self.conn, date(2026,10,1))[1]
        self.assertEqual(product['_quantity'], Decimal('46'))
        self.assertEqual(product['status'], 'available')
        self.assertLessEqual(self.reservation_reads(), 1)
