import copy
import json
import unittest

from app.db import connect_db
from app.products import create_product
from tests import test_app
from tools.import_owner_responses import apply_responses


class OwnerResponseTest(unittest.TestCase):
    def setUp(self):
        test_app.AppTest.setUp(self)
        self.conn = connect_db(self.app.config['DB_PATH'])
        self.addCleanup(self.conn.close)
        product = create_product(self.conn, {'code': 'SKU', 'name': '味精', 'unit': '罐', 'category': '調味'}, 1)
        self.pid = product['id']
        self.conn.execute("UPDATE batches SET source='inventory.xlsx/庫存管理/115' WHERE product_id=?", (self.pid,))
        self.conn.execute("INSERT INTO invoice_items(id,source,category,code,name,price,unit,tax,kind) VALUES(77,'invoice.xlsx/易發票系統/26','1','EXT','味全味精','75','瓶',1,0)")
        self.document = {'schema': 'duck.owner-review.response.v2', 'tasks': [{
            'id': 'invoice_items:25:mapping', 'source': {'title': '味精品牌確認',
                'target': {'table': 'invoice_items', 'id': 25, 'field': 'product_id'},
                'original': {'source': 'invoice.xlsx/易發票系統/26', 'category': '1', 'code': 'EXT',
                    'name': '味全味精', 'price': '75', 'unit': '瓶', 'tax': 1, 'kind': 0},
                'candidates': [{'id': 113, 'code': 'SKU', 'name': '味精', 'unit': '罐', 'category': '調味',
                    'inventory_sources': ['inventory.xlsx/庫存管理/115']}]},
            'response': {'status': 'confirmed', 'decision': 'match', 'product_id': 113, 'choice': 'same:113'}}]}

    def test_remaps_snapshot_ids_by_verified_source_and_preserves_stock(self):
        before = [tuple(r) for r in self.conn.execute('SELECT * FROM batches')]
        report = apply_responses(self.conn, self.document)
        row = self.conn.execute('SELECT * FROM invoice_items WHERE id=77').fetchone()
        self.assertEqual(row['product_id'], self.pid)
        self.assertEqual(row['unit'], '罐')
        self.assertEqual(row['code'], 'EXT')
        self.assertEqual(before, [tuple(r) for r in self.conn.execute('SELECT * FROM batches')])
        self.conn.execute('UPDATE invoice_items SET product_id=NULL')
        self.assertEqual(apply_responses(self.conn, self.document), report)
        self.assertIsNone(self.conn.execute('SELECT product_id FROM invoice_items').fetchone()[0])

    def test_stale_or_unconfirmed_or_invalid_candidate_rejected(self):
        for field, value in [('status', 'pending'), ('product_id', 1), ('choice', 'same:999')]:
            document = copy.deepcopy(self.document)
            document['tasks'][0]['response'][field] = value
            with self.assertRaises(ValueError):
                apply_responses(self.conn, document)
        self.conn.execute("UPDATE invoice_items SET name='已改名'")
        with self.assertRaises(ValueError):
            apply_responses(self.conn, self.document)
        self.assertIsNone(self.conn.execute('SELECT product_id FROM invoice_items').fetchone()[0])

    def test_conflicting_existing_mapping_rejected(self):
        self.conn.execute('UPDATE invoice_items SET fixed=1')
        with self.assertRaises(ValueError):
            apply_responses(self.conn, self.document)

    def test_wrong_stock_source_rejected(self):
        self.conn.execute("UPDATE batches SET source='other.xlsx/庫存管理/115'")
        with self.assertRaises(ValueError):
            apply_responses(self.conn, self.document)

    def test_independent_decision_keeps_original_price_and_no_stock_link(self):
        self.conn.execute("INSERT INTO catalog_cards(id,source,brand,name,specification,original_price) VALUES(8,'rice!K17','品牌','牛奶糙米','1.5kg','170')")
        document = {'schema': 'duck.owner-review.response.v2', 'tasks': [{
            'source': {'title': '是否相同', 'target': {'table': 'catalog_cards', 'id': 79, 'field': 'product_id'},
                'original': {'source': 'rice!K17', 'brand': '品牌', 'name': '牛奶糙米', 'specification': '1.5kg', 'original_price': '170'}},
            'response': {'status': 'confirmed', 'decision': 'independent', 'choice': 'different'}}]}
        apply_responses(self.conn, document)
        self.assertEqual(tuple(self.conn.execute('SELECT product_id,independent,original_price,pricing_mode FROM catalog_cards').fetchone()),
                         (None, 1, '170', 'fixed'))

    def test_import_normalization_preserves_batches_and_original(self):
        from tools.import_raw_data import normalized_preview
        rows = [{'code': ' DUP ', 'name': name, 'unit': unit, 'category': ' A ', 'supplier': ' S ',
                 'quantity': quantity, 'expires_on': expiry}
                for name, unit, quantity, expiry in [('甲', ' Kg ', None, None), ('甲', ' Kg ', '0', '2027-01-01'), ('乙', '包', '2', '2027-05-01')]]
        original = {'rows': rows}
        before = copy.deepcopy(original)
        result = normalized_preview(original)
        self.assertEqual(original, before)
        self.assertEqual([r['code'] for r in result['rows']], ['DUP-01', 'DUP-01', 'DUP-02'])
        self.assertEqual([r['quantity'] for r in result['rows']], [None, '0', '2'])
        self.assertEqual(result['rows'][0]['unit'], 'kg')
