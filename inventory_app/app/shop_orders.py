import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from .common import Problem, decimal_text, mutate, now, record, required_text, transaction, valid_date
from .reservations import expire_orders, reserved_quantity
from .shop_catalog import quote, settings

STATUS={'pending':'待店家確認','confirmed':'已確認，準備中','ready':'可以取貨','picked_up':'已取貨付款','cancelled':'已取消','expired':'已超過取貨期限'}


def token_for(secret, oid, request_id, client):
    return hmac.new(str(secret).encode(),f'{oid}:{request_id}:{client}'.encode(),hashlib.sha256).hexdigest()


def order_view(conn, row, admin=False):
    r=dict(row)
    if r['status'] in {'pending','confirmed','ready'} and r['hold_until']<now():r['status']='expired'
    keep=('id','number','status','name','pickup_date','pickup_slot','hold_until','total','created_at','updated_at')
    result={k:r[k] for k in keep}
    if admin:result['phone']=r['phone']
    result.update(status_label=STATUS[r['status']],items=json.loads(r['snapshot'])['items'],groups=json.loads(r['snapshot'])['groups'])
    result['events']=[dict(x) for x in conn.execute('SELECT status,created_at FROM order_events WHERE order_id=? ORDER BY id',(r['id'],))]
    return result


def create_order(conn, body, client_hash, rate_hash, day, secret):
    request_id=required_text(body.get('request_id'),'訂單識別碼',100)
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with transaction(conn):
        expire_orders(conn)
        old=conn.execute('SELECT * FROM customer_orders WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old['payload_hash']!=digest or old['client_hash']!=client_hash:raise Problem('訂單識別碼已使用，請重新送單',status=409)
            return {**order_view(conn,old),'token':token_for(secret,old['id'],request_id,client_hash)},False
        config=settings(conn)
        if not config.get('enabled') or not config.get('slots'):raise Problem('店家尚未開放接單，請稍後再試',status=409)
        name=required_text(body.get('name'),'取貨姓名',40)
        phone=required_text(body.get('phone'),'聯絡電話',30)
        if not re.fullmatch(r'[0-9+()\s-]{8,25}',phone) or len(re.sub(r'\D','',phone))<8:raise Problem('請填有效的聯絡電話')
        pickup=valid_date(body.get('pickup_date'),optional=False)
        if not day.isoformat()<=pickup<=(day+timedelta(days=14)).isoformat():raise Problem('請選今天起14天內的取貨日期')
        slot=body.get('pickup_slot')
        if slot not in config['slots']:raise Problem('取貨時段已變更，請重新選擇')
        end=slot.split('–')[-1]
        until=datetime.fromisoformat(pickup+'T'+end+':00').replace(tzinfo=ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')
        if until<=now():raise Problem('這個取貨時段已結束，請選其他時段')
        q=quote(conn,body,day)
        if q['revision']!=body.get('quote_revision'):raise Problem('商品價格或內容已更新，請重新確認購物車',code='quote_changed',status=409)
        if q['issues']:raise Problem('部分商品目前無法訂購，請調整購物車',status=409,fields={'issues':q['issues']})
        # Check expiry through the selected pickup day, without reserving pending orders.
        for item in q['items']:
            bs=conn.execute('SELECT * FROM batches WHERE product_id=? AND saleable=1 AND expires_on>=?',(item['id'],pickup)).fetchall()
            amount=sum((max(Decimal(0),Decimal(b['quantity'])-reserved_quantity(conn,b['id'])) for b in bs if b['quantity'] is not None),Decimal(0))
            if amount<Decimal(item['quantity']):raise Problem(item['name']+'在所選取貨日無足夠有效期庫存',status=409)
        stamp=int(time.time());conn.execute('DELETE FROM shop_attempts WHERE created_at<?',(stamp-3600,))
        if conn.execute('SELECT COUNT(*) FROM shop_attempts WHERE client_hash=?',(rate_hash,)).fetchone()[0]>=10:
            raise Problem('送單次數較多，請稍後再試或聯絡店家',status=429)
        conn.execute('INSERT INTO shop_attempts VALUES(?,?)',(rate_hash,stamp))
        oid=uuid4().hex;token=token_for(secret,oid,request_id,client_hash);number=day.strftime('%Y%m%d')+'-'+oid[:8].upper()
        conn.execute('''INSERT INTO customer_orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (oid,number,hashlib.sha256(token.encode()).hexdigest(),client_hash,request_id,digest,'pending',name,phone,pickup,slot,until,q['total'],json.dumps(q,ensure_ascii=False),now(),now()))
        conn.executemany('INSERT INTO order_items VALUES(?,?,?,?,?,?)',[(oid,i['id'],i['name'],i['unit'],i['quantity'],i['price']) for i in q['items']])
        conn.execute('INSERT INTO order_events(order_id,status,actor,created_at) VALUES(?,?,?,?)',(oid,'pending','customer',now()))
        row=conn.execute('SELECT * FROM customer_orders WHERE id=?',(oid,)).fetchone()
        return {**order_view(conn,row),'token':token},True


def transition_order(conn, oid, action, actor, request_id, day):
    def apply():
        expire_orders(conn)
        order=conn.execute('SELECT * FROM customer_orders WHERE id=?',(oid,)).fetchone()
        if not order:raise Problem('找不到訂單',status=404)
        transitions={'confirm':({'pending'},'confirmed'),'ready':({'confirmed'},'ready'),
                     'pickup':({'ready'},'picked_up'),'cancel':({'pending','confirmed','ready'},'cancelled')}
        if action not in transitions or order['status'] not in transitions[action][0]:raise Problem('訂單狀態已更新，請重新查看',status=409)
        status=transitions[action][1]
        if action=='confirm':
            for item in conn.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY product_id',(oid,)).fetchall():
                if conn.execute('SELECT 1 FROM batches WHERE product_id=? AND quantity IS NULL',(item['product_id'],)).fetchone():
                    raise Problem(item['name']+'尚未盤點完成',status=409)
                left=Decimal(item['quantity'])
                batches=conn.execute('''SELECT * FROM batches WHERE product_id=? AND saleable=1 AND expires_on>=?
                    ORDER BY expires_on,id''',(item['product_id'],max(day.isoformat(),order['pickup_date']))).fetchall()
                for b in batches:
                    if b['quantity'] is None:continue
                    quantity=min(left,max(Decimal(0),Decimal(b['quantity'])-reserved_quantity(conn,b['id'])))
                    if quantity>0:
                        conn.execute('INSERT INTO reservations VALUES(?,?,?)',(oid,b['id'],decimal_text(quantity)))
                        left-=quantity
                    if left==0:break
                if left>0:raise Problem(item['name']+'可預留庫存不足，尚未確認此訂單',status=409)
        if action=='pickup':
            rs=conn.execute('SELECT r.*,b.product_id,b.quantity AS physical,b.saleable,b.expires_on FROM reservations r JOIN batches b ON b.id=r.batch_id WHERE order_id=? ORDER BY batch_id',(oid,)).fetchall()
            totals={}
            for r in rs:
                totals[r['product_id']]=totals.get(r['product_id'],Decimal(0))+Decimal(r['quantity'])
                if r['physical'] is None or not r['saleable'] or not r['expires_on'] or r['expires_on']<day.isoformat() or Decimal(r['physical'])<reserved_quantity(conn,r['batch_id']):
                    raise Problem('預留批次已變更或過期，請先處理訂單，不能直接交付',status=409)
            expected={i['product_id']:Decimal(i['quantity']) for i in conn.execute('SELECT * FROM order_items WHERE order_id=?',(oid,))}
            if totals!=expected:raise Problem('預留內容不完整，不能交付',status=409)
            for r in rs:
                after=decimal_text(Decimal(r['physical'])-Decimal(r['quantity']))
                conn.execute('UPDATE batches SET quantity=?,version=version+1 WHERE id=?',(after,r['batch_id']))
                record(conn,r['product_id'],r['batch_id'],'issue','客人訂單 '+order['number'],r['physical'],after,actor)
        if action in {'pickup','cancel'}:conn.execute('DELETE FROM reservations WHERE order_id=?',(oid,))
        conn.execute('UPDATE customer_orders SET status=?,updated_at=? WHERE id=?',(status,now(),oid))
        conn.execute('INSERT INTO order_events(order_id,status,actor,created_at) VALUES(?,?,?,?)',(oid,status,str(actor),now()))
        return order_view(conn,conn.execute('SELECT * FROM customer_orders WHERE id=?',(oid,)).fetchone(),admin=True)
    return mutate(conn,request_id,{'operation':'customer-order','id':oid,'action':action},apply)
