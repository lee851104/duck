import json
import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
from uuid import uuid4

from tests import test_app
from app.db import connect_db
from app.products import create_product, update_product
from app.inventory import count_stock, issue, reverse_movement
from app.common import Problem
from app.shop_catalog import initialize_shop
from app.shop_orders import transition_order
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


class ShopTest(unittest.TestCase):
    login = test_app.AppTest.login

    def setUp(self):
        clock = patch('app.common.datetime', wraps=datetime)
        fixed_clock = clock.start()
        self.addCleanup(clock.stop)
        fixed_clock.now.return_value = datetime(2026, 10, 1, 9, tzinfo=ZoneInfo('Asia/Taipei'))
        test_app.AppTest.setUp(self)
        self.app.config['CUSTOMER_ORDERING_ENABLED'] = True  # Legacy order compatibility tests only.
        self.login()
        self.admin = self.client
        self.headers = {'X-CSRF-Token':self.token}
        self.conn = connect_db(self.app.config['DB_PATH'])
        self.addCleanup(self.conn.close)
        self.products = {}
        for code,name,unit,price in [('C19002','番茄牛肉湯','包','110'),('C15001','烏龍麵','包','135'),
             ('B10006','雞腿','包','150'),('F07001','醬油','瓶','55'),('F07003','味醂','瓶','55'),
             ('J03001','玉米粒','罐','35'),('D15003','貢丸','包','180'),('H99004','雞湯塊','盒','45')]:
            p=create_product(self.conn,{'code':code,'name':name,'unit':unit,'price':price,'supplier':'private supplier'},1)
            b=self.conn.execute('SELECT id FROM batches WHERE product_id=?',(p['id'],)).fetchone()[0]
            count_stock(self.conn,{'batch_id':b,'expected_version':1,'actual_quantity':'5','expires_on':'2027-12-31',
                                 'saleable_confirmed':True,'request_id':str(uuid4())},1)
            self.products[code]={**p,'batch':b}
        initialize_shop(self.conn, publish_existing=True)
        self.conn.execute("INSERT OR REPLACE INTO metadata VALUES('shop_settings',?)",(json.dumps({'slots':['10:00–12:00','16:00–18:00'],'enabled':True}),))
        self.guest=self.app.test_client()
        self.guest_headers={'X-CSRF-Token':self.guest.get('/api/shop/session').get_json()['csrf']}

    def selection(self,code='C19002',quantity=1):
        return {'items':[{'product_id':self.products[code]['id'],'quantity':quantity}],'recipes':[]}

    def post(self,path,body):
        return self.guest.post('/api/shop/'+path,json=body,headers=self.guest_headers)

    def place(self,selection=None,request_id=None):
        selection=selection or self.selection()
        quote=self.post('quote',selection).get_json()
        body={**selection,'quote_revision':quote['revision'],'request_id':request_id or str(uuid4()),
              'name':'測試客人','phone':'0912345678','pickup_date':'2026-10-02','pickup_slot':'10:00–12:00'}
        return self.post('orders',body),body

    def transition(self,oid,action,key=None):
        return self.admin.post(f'/api/customer-orders/{oid}/transition',json={'action':action,'request_id':key or str(uuid4())},headers=self.headers)

    def test_google_mode_guests_order_without_login_but_require_contact_details(self):
        self.app.config['AUTH_MODE'] = 'google'
        selection = self.selection()
        quote = self.post('quote', selection).get_json()
        body = {**selection, 'quote_revision': quote['revision'], 'request_id': str(uuid4()),
                'name': '測試客人', 'phone': '0912345678', 'pickup_date': '2026-10-02',
                'pickup_slot': '10:00–12:00'}
        for field in ['name', 'phone', 'pickup_date', 'pickup_slot']:
            invalid = {**body, field: ''}
            self.assertEqual(self.post('orders', invalid).status_code, 400)
        self.assertEqual(self.post('orders', {**body, 'phone': 'not-a-phone'}).status_code, 400)
        self.assertEqual(self.post('orders', body).status_code, 201)
        self.assertFalse(self.guest.get('/api/session').get_json()['authenticated'])
        self.assertEqual(self.guest.get('/api/customer-orders').status_code, 401)

    def test_public_projection_and_three_recipes(self):
        self.assertEqual(self.guest.get('/shop').status_code,200)
        data=self.guest.get('/api/shop/catalog').get_json()
        self.assertEqual(data['total'],8)
        serialized=json.dumps(data)
        for private in ['supplier','cost','batches','private supplier','received_on']:
            self.assertNotIn(private,serialized)
        recipes=self.guest.get('/api/shop/recipes').get_json()['items']
        self.assertEqual(len(recipes),3)
        self.assertEqual([r['total'] for r in recipes],['245','260','260'])
        self.assertEqual(self.guest.get('/api/products').status_code,401)
        self.assertEqual(self.guest.get('/api/customer-orders').status_code,401)

    def test_catalog_category_order_photos_first_and_all_items(self):
        self.conn.execute("UPDATE products SET category='B冷凍',image=NULL")
        first=self.products['F07001']['id']
        second=self.products['C19002']['id']
        photo=self.products['C15001']['id']
        self.conn.execute("UPDATE products SET category='A乳品' WHERE id=?",(first,))
        self.conn.execute("UPDATE products SET image='photo.png' WHERE id=?",(photo,))
        # Cross a normal page boundary; missing/unknown stock must remain visible.
        for index in range(25):
            create_product(self.conn,{'code':f'Z{index:02}', 'name':f'待盤點{index}',
                           'unit':'包','category':'Z其他'},1)
        self.conn.execute('INSERT OR IGNORE INTO shop_products SELECT id,1 FROM products')
        hidden=create_product(self.conn,{'code':'HIDDEN','name':'未上架','unit':'包'},1)
        self.conn.execute('INSERT OR REPLACE INTO shop_products VALUES(?,0)',(hidden['id'],))
        data=self.guest.get('/api/shop/catalog?all=1').get_json()
        self.assertEqual(data['total'],33)
        self.assertEqual(len(data['items']),33)
        self.assertEqual(len({p['id'] for p in data['items']}),33)
        self.assertEqual(data['categories'],['乳品','冷凍','其他'])
        ids=[p['id'] for p in data['items']]
        self.assertEqual(ids[:2],[first,photo])
        self.assertGreater(ids.index(second),ids.index(photo))
        self.assertNotIn(hidden['id'],ids)
        filtered=self.guest.get('/api/shop/catalog?all=1&category=冷凍').get_json()
        self.assertEqual(filtered['total'],7)
        self.assertEqual(filtered['items'][0]['id'],photo)
        self.assertTrue(all(p['category']=='冷凍' for p in filtered['items']))

    def test_recipe_condiments_and_shared_product_sum(self):
        recipes=self.guest.get('/api/shop/recipes').get_json()['items']
        chicken=next(r for r in recipes if r['slug']=='teriyaki-chicken')
        omit=[self.products[c]['id'] for c in ('F07001','F07003')]
        response=self.post('quote',{'recipes':[{'recipe_id':chicken['id'],'quantity':1,'omit':omit}],
                                   'items':[{'product_id':self.products['B10006']['id'],'quantity':1}]})
        self.assertEqual(response.status_code,200,response.get_json())
        self.assertEqual(response.get_json()['total'],'300')
        self.assertEqual(response.get_json()['items'][0]['quantity'],'2')
        response=self.post('quote',{'recipes':[{'recipe_id':chicken['id'],'quantity':1,'omit':[self.products['B10006']['id']]}]})
        self.assertEqual(response.status_code,400)

    def test_pending_confirm_pickup_is_exactly_once(self):
        response,body=self.place();self.assertEqual(response.status_code,201,response.get_json())
        order=response.get_json();bid=self.products['C19002']['batch']
        self.assertEqual(self.conn.execute('SELECT quantity FROM batches WHERE id=?',(bid,)).fetchone()[0],'5')
        retry=self.post('orders',body);self.assertEqual(retry.get_json()['token'],order['token'])
        self.assertEqual(self.transition(order['id'],'confirm').status_code,200)
        self.assertEqual(self.transition(order['id'],'ready').status_code,200)
        self.assertEqual(self.transition(order['id'],'pickup').status_code,200)
        self.assertEqual(self.transition(order['id'],'pickup').status_code,409)
        self.assertEqual(self.conn.execute('SELECT quantity FROM batches WHERE id=?',(bid,)).fetchone()[0],'4')
        status=self.post('order-status',{'token':order['token']}).get_json()
        self.assertEqual(status['status'],'picked_up')
        mid=self.conn.execute("SELECT id FROM movements WHERE reason LIKE '客人訂單 %'").fetchone()[0]
        with self.assertRaises(Problem):
            reverse_movement(self.conn,mid,'錯誤沖銷',str(uuid4()),1)
        self.assertEqual(self.post('order-status',{'token':str(order['id'])}).status_code,404)

    def test_concurrent_confirm_and_cancel_release(self):
        a,_=self.place(self.selection(quantity=4));b,_=self.place(self.selection(quantity=4))
        aid,bid=a.get_json()['id'],b.get_json()['id']
        self.assertEqual(self.transition(aid,'confirm').status_code,200)
        self.assertEqual(self.transition(bid,'confirm').status_code,409)
        self.assertEqual(self.transition(aid,'cancel').status_code,200)
        self.assertEqual(self.transition(bid,'confirm').status_code,200)

    def test_reservations_block_walkin_count_and_expiry_change(self):
        a,_=self.place(self.selection(quantity=4));self.transition(a.get_json()['id'],'confirm')
        p=self.products['C19002'];b=self.conn.execute('SELECT * FROM batches WHERE id=?',(p['batch'],)).fetchone()
        other=self.products['C15001']
        other_batch=self.conn.execute('SELECT * FROM batches WHERE id=?',(other['batch'],)).fetchone()
        response=self.admin.post('/api/counts/bulk',json={'request_id':str(uuid4()),'items':[
            {'batch_id':other_batch['id'],'expected_version':other_batch['version'],'actual_quantity':'1'},
            {'batch_id':b['id'],'expected_version':b['version'],'actual_quantity':'2'}]},headers=self.headers)
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.conn.execute('SELECT quantity FROM batches WHERE id=?',(other_batch['id'],)).fetchone()[0],'5')
        with self.assertRaises(Problem):
            issue(self.conn,{'product_id':p['id'],'reason':'銷售','request_id':str(uuid4()),
                            'allocations':[{'batch_id':b['id'],'quantity':'2','expected_version':b['version']}]},1,date(2026,10,1))
        with self.assertRaises(Problem):
            count_stock(self.conn,{'batch_id':b['id'],'actual_quantity':'2','expected_version':b['version'],
                                  'request_id':str(uuid4())},1)
        with self.assertRaises(Problem):
            count_stock(self.conn,{'batch_id':b['id'],'actual_quantity':'5','expected_version':b['version'],
                                  'expires_on':'2026-10-01','request_id':str(uuid4())},1)

    def test_unknown_price_change_invalid_payload_and_csrf(self):
        selection=self.selection();q=self.post('quote',selection).get_json()
        p=self.products['C19002'];update_product(self.conn,p['id'],{'price':'120'},1,1)
        _,body=self.place(selection);body['request_id']=str(uuid4());body['quote_revision']=q['revision']
        self.assertEqual(self.post('orders',body).status_code,409)
        self.conn.execute('UPDATE batches SET quantity=NULL WHERE product_id=?',(p['id'],))
        r,_=self.place(selection);self.assertEqual(r.status_code,409)
        self.assertEqual(self.guest.post('/api/shop/orders',json={}).status_code,403)
        for invalid in [0,-1,1.5,'NaN',True]:
            self.assertEqual(self.post('quote',self.selection(quantity=invalid)).status_code,400)

    def test_unpublished_product_not_orderable(self):
        pid=self.products['C19002']['id']
        self.conn.execute('UPDATE shop_products SET published=0 WHERE product_id=?',(pid,))
        self.assertEqual(self.post('quote',self.selection()).status_code,400)

    def test_lost_response_recovered_only_by_original_client(self):
        response,body=self.place();order=response.get_json()
        recovered=self.post('recover-order',{'request_id':body['request_id']})
        self.assertEqual(recovered.status_code,200)
        self.assertEqual(recovered.get_json()['order']['token'],order['token'])
        stranger=self.app.test_client();csrf=stranger.get('/api/shop/session').get_json()['csrf']
        result=stranger.post('/api/shop/recover-order',json={'request_id':body['request_id']},headers={'X-CSRF-Token':csrf})
        self.assertIsNone(result.get_json()['order'])
        self.assertIsNone(self.post('recover-order',{'request_id':str(uuid4())}).get_json()['order'])

    def test_public_payload_limit(self):
        result=self.post('quote',{'items':[],'padding':'x'*70000})
        self.assertEqual(result.status_code,413)

    def race(self,commands):
        barrier=Barrier(2)
        def run(command):
            c=connect_db(self.app.config['DB_PATH'])
            try:
                barrier.wait(timeout=10)
                try:command(c);return True
                except Problem:return False
            finally:c.close()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run,commands))

    def test_two_connections_confirm_compete(self):
        ids=[self.place(self.selection(quantity=4))[0].get_json()['id'] for _ in range(2)]
        result=self.race([lambda c,oid=oid:transition_order(c,oid,'confirm',1,str(uuid4()),date(2026,10,1)) for oid in ids])
        self.assertEqual(sorted(result),[False,True])
        self.assertEqual(self.conn.execute('SELECT SUM(CAST(quantity AS INTEGER)) FROM reservations').fetchone()[0],4)

    def test_confirmation_competes_with_walkin_sale(self):
        oid=self.place(self.selection(quantity=4))[0].get_json()['id'];p=self.products['C19002']
        b=self.conn.execute('SELECT * FROM batches WHERE id=?',(p['batch'],)).fetchone()
        result=self.race([lambda c:transition_order(c,oid,'confirm',1,str(uuid4()),date(2026,10,1)),
            lambda c:issue(c,{'product_id':p['id'],'reason':'銷售','request_id':str(uuid4()),'allocations':[
                {'batch_id':b['id'],'quantity':'4','expected_version':b['version']}]},1,date(2026,10,1))])
        self.assertEqual(sorted(result),[False,True])

    def test_timeout_release_replay_and_rate_limit(self):
        oid=self.place(self.selection(quantity=4))[0].get_json()['id'];self.transition(oid,'confirm')
        self.conn.execute("UPDATE customer_orders SET hold_until='2020-01-01T00:00:00+08:00' WHERE id=?",(oid,))
        next_id=self.place(self.selection(quantity=4))[0].get_json()['id']
        self.assertEqual(self.transition(next_id,'confirm').status_code,200)
        self.assertEqual(self.conn.execute('SELECT status FROM customer_orders WHERE id=?',(oid,)).fetchone()[0],'expired')
        self.transition(next_id,'ready');key=str(uuid4())
        self.assertEqual(self.transition(next_id,'pickup',key).status_code,200)
        self.assertEqual(self.transition(next_id,'pickup',key).status_code,200)
        self.assertEqual(self.conn.execute('SELECT quantity FROM batches WHERE id=?',(self.products['C19002']['batch'],)).fetchone()[0],'1')
        for _ in range(8):self.assertEqual(self.place()[0].status_code,201)
        self.guest=self.app.test_client();self.guest_headers={'X-CSRF-Token':self.guest.get('/api/shop/session').get_json()['csrf']}
        self.assertEqual(self.place()[0].status_code,429)

    def test_shared_sku_across_recipes_and_snapshot(self):
        rs=self.guest.get('/api/shop/recipes').get_json()['items'];a,b=rs[0]['id'],rs[1]['id'];pid=self.products['C19002']['id']
        self.conn.execute('INSERT INTO recipe_items VALUES(?,?,1,0)',(b,pid))
        selection={'recipes':[{'recipe_id':a,'quantity':1},{'recipe_id':b,'quantity':1}]}
        q=self.post('quote',selection).get_json()
        self.assertEqual(next(i for i in q['items'] if i['id']==pid)['quantity'],'2')
        result,_=self.place(selection);order=result.get_json();self.assertEqual(order['total'],'615')
        self.conn.execute("UPDATE products SET price='999' WHERE id=?",(pid,))
        self.assertEqual(self.post('order-status',{'token':order['token']}).get_json()['total'],'615')

    def test_expired_reservation_and_batch_not_delivered(self):
        a,_=self.place();oid=a.get_json()['id'];self.transition(oid,'confirm')
        self.conn.execute("UPDATE batches SET expires_on='2026-09-30' WHERE id=?",(self.products['C19002']['batch'],))
        self.transition(oid,'ready')
        self.assertEqual(self.transition(oid,'pickup').status_code,409)
        self.assertEqual(self.transition(oid,'cancel').status_code,200)


if __name__=='__main__':unittest.main()
