import unittest
from tests import test_app


class QueriesTest(unittest.TestCase):
    login = test_app.AppTest.login

    def setUp(self):
        test_app.AppTest.setUp(self)
        self.login()
        self.headers={'X-CSRF-Token':self.token}
        self.p=self.client.post('/api/products',json={'code':'T1','name':'芋頭貢丸','unit':'包','price':'150'},headers=self.headers).get_json()

    def test_search_and_page_limit(self):
        result=self.client.get('/api/products?q=芋頭&page_size=100').get_json()
        self.assertEqual(result['total'],1)
        self.assertEqual(result['page_size'],10)
        self.assertEqual(self.client.get('/api/products?page_size=0').status_code,400)

    def test_catalog_category_order_and_missing_photos_kept(self):
        from app.db import connect_db
        from contextlib import closing
        with closing(connect_db(self.app.config['DB_PATH'])) as c:
            c.execute("UPDATE products SET category='Z其他' WHERE id=?",(self.p['id'],))
            for source,name,image in [('10其他!A1','後分類有圖','ten.png'),
                                      ('2海鮮!A1','同類缺圖',None),
                                      ('2海鮮!A2','同類有圖','two.png')]:
                c.execute('INSERT INTO catalog_cards(source,name,image) VALUES(?,?,?)',
                          (source,name,image))
        data=self.client.get('/api/catalog').get_json()
        self.assertEqual(data['total'],4)
        self.assertEqual([p['name'] for p in data['items'][:3]],
                         ['同類有圖','同類缺圖','後分類有圖'])
        self.assertEqual(data['photo_counts'],{'all':4,'present':2,'missing':2})

    def test_catalog_gallery_paging_and_photo_filters(self):
        from app.db import connect_db
        c=connect_db(self.app.config['DB_PATH'])
        for i in range(30):
            c.execute('INSERT INTO catalog_cards(source,name,image) VALUES(?,?,?)',
                      (f'gallery-{i}',f'照片商品{i}', 'sample.thumb.jpg' if i<27 else None))
        c.close()
        first=self.client.get('/api/catalog?page_size=24&photos=present').get_json()
        self.assertEqual(len(first['items']),24)
        self.assertEqual(first['total'],27)
        second=self.client.get('/api/catalog?page=2&page_size=24&photos=present').get_json()
        self.assertEqual(len(second['items']),3)
        self.assertFalse({x['id'] for x in first['items']} & {x['id'] for x in second['items']})
        missing=self.client.get('/api/catalog?photos=missing&page_size=48').get_json()
        self.assertEqual(missing['total'],4)
        self.assertTrue(all(not x.get('image') for x in missing['items']))
        self.assertEqual(first['photo_counts'],{'all':31,'present':27,'missing':4})

    def test_dashboard_unknown_matches_inventory(self):
        dashboard=self.client.get('/api/dashboard').get_json()
        products=self.client.get('/api/products?status=uncounted').get_json()
        self.assertEqual(dashboard['uncounted_products'],products['total'])
        self.assertEqual(dashboard['out_of_stock_products'],0)

    def test_product_detail_and_batched_count(self):
        batches=self.client.get(f'/api/products/{self.p["id"]}/batches').get_json()
        batch=batches['items'][0]
        response=self.client.post('/api/counts',json={'batch_id':batch['id'],'actual_quantity':'5',
                  'expected_version':batch['version'],'request_id':'count-001',
                  'expires_on':'2027-01-01','saleable_confirmed':True},headers=self.headers)
        self.assertEqual(response.status_code,200,response.get_json())
        detail=self.client.get(f'/api/products/{self.p["id"]}').get_json()
        self.assertEqual(detail['quantity'],'5')

    def test_home_and_js_are_served(self):
        self.assertEqual(self.client.get('/').status_code,200)
        with self.client.get('/static/app.js') as response:
            self.assertEqual(response.status_code,200)

    def test_unknown_product_404(self):
        self.assertEqual(self.client.get('/api/products/99999').status_code,404)

    def test_bad_operation_payloads(self):
        self.assertEqual(self.client.post('/api/issues',json={'request_id':'bad','product_id':self.p['id'],
            'reason':'銷售','allocations':[]},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/receipts',json={'request_id':'bad2','product_id':self.p['id'],
            'quantity':'1','cost':'NaN','received_on':'2026-10-01','unknown_expiry':True},headers=self.headers).status_code,400)

    def test_mapping_revision_logged(self):
        from app.db import connect_db
        c=connect_db(self.app.config['DB_PATH'])
        c.execute("INSERT INTO catalog_cards(source,name,original_price) VALUES('A!E11','貢丸','150')")
        c.close()
        result=self.client.post('/api/mappings/catalog/1',json={'product_id':self.p['id'],
              'pricing_mode':'product'},headers=self.headers)
        self.assertEqual(result.status_code,200,result.get_json())
        self.assertEqual(self.client.get('/api/catalog').get_json()['items'][0]['price'],'150')

    def test_new_product_appears_with_existing_catalog_cards(self):
        from app.db import connect_db
        c=connect_db(self.app.config['DB_PATH'])
        c.execute("INSERT INTO catalog_cards(source,name,product_id) VALUES('A!E11','舊圖卡',?)",(self.p['id'],))
        c.close()
        newer=self.client.post('/api/products',json={'code':'NEW','name':'新增商品','unit':'包','price':'99'},headers=self.headers).get_json()
        catalog=self.client.get('/api/catalog?q=新增商品').get_json()
        self.assertEqual(catalog['total'],1)
        self.assertEqual(catalog['items'][0]['product_id'],newer['id'])

    def test_meta_includes_source_catalog_categories(self):
        from app.db import connect_db
        c=connect_db(self.app.config['DB_PATH'])
        c.execute("INSERT INTO catalog_cards(source,name) VALUES('7豬肉!E11','原始圖卡')")
        c.close()
        self.assertIn('7豬肉',self.client.get('/api/meta').get_json()['catalog_categories'])

    def test_new_product_can_join_invoice_export(self):
        result=self.client.post('/api/invoice-items',json={'product_id':self.p['id'],
            'category':'1734','tax':1,'request_id':'new-invoice-item'},headers=self.headers)
        self.assertEqual(result.status_code,200,result.get_json())
        repeated=self.client.post('/api/invoice-items',json={'product_id':self.p['id'],
            'category':'1734','tax':1,'request_id':'new-invoice-item'},headers=self.headers)
        self.assertEqual(repeated.get_json(),result.get_json())
        rows=self.client.get('/api/mappings/invoice').get_json()
        self.assertEqual(rows['total'],1)
        self.assertEqual(rows['items'][0]['product_id'],self.p['id'])
