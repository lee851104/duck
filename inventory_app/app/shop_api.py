import base64
import hashlib
import io
import json
import re
import secrets
from datetime import timedelta

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_file, session
from PIL import Image, ImageOps, UnidentifiedImageError

from .common import Problem, paginate, required_text, today, transaction
from .db import get_db
from .reservations import expire_orders
from .shop_catalog import initialize_shop, integer, product_map, public_product, quote, recipe_catalog, settings
from .shop_orders import create_order, order_view, transition_order, token_for

shop=Blueprint('shop',__name__)


@shop.before_request
def merchant_only():
    # Keep historical orders available to the owner, but close customer ordering.
    if current_app.config.get('CUSTOMER_ORDERING_ENABLED', False):
        return
    if request.path == '/shop':
        return redirect('/#daily-sales')
    if request.path.startswith('/api/shop/') or (request.path.startswith('/shop/media/') and not session.get('user')):
        raise Problem('客人下單功能已停用，請洽店家', status=410)
    if request.path == '/api/shop-admin/settings' and request.method == 'POST':
        raise Problem('目前使用每日銷售單，客人接單已停用', status=410)


@shop.get('/shop')
def home():return render_template('shop.html')


@shop.get('/shop/manage')
def manage():
    if not session.get('user'):return redirect('/')
    return render_template('shop_admin.html')


@shop.get('/api/shop/session')
def public_session():
    session.setdefault('csrf',secrets.token_urlsafe(32))
    session.setdefault('shop_client',secrets.token_urlsafe(32))
    return jsonify(csrf=session['csrf'],today=today().isoformat(),max_date=(today()+timedelta(days=14)).isoformat(),
                   settings=settings(get_db()),demo=current_app.config.get('DEMO',False))


@shop.get('/api/shop/catalog')
def catalog():
    rows=[public_product(p) for p in product_map(get_db(),today()).values()]
    categories=list(dict.fromkeys(p['category'] for p in rows))
    q=request.args.get('q','').casefold();category=request.args.get('category','')
    rows=[p for p in rows if (not q or q in p['name'].casefold()) and (not category or p['category']==category)]
    if request.args.get('all') == '1':
        return jsonify(items=rows,total=len(rows),page=1,page_size=max(1,len(rows)),categories=categories)
    return jsonify({**paginate(rows,request.args.get('page',1),24,maximum=24),'categories':categories})


@shop.get('/api/shop/recipes')
def recipes():return jsonify(items=recipe_catalog(get_db(),today()))


@shop.post('/api/shop/quote')
def price_quote():return jsonify(quote(get_db(),request.get_json(),today()))


@shop.post('/api/shop/orders')
def submit_order():
    client=session.get('shop_client')
    if not client:raise Problem('請重新整理頁面後送單',status=403)
    rate=hashlib.sha256((str(current_app.secret_key)+(request.remote_addr or '')).encode()).hexdigest()
    result,created=create_order(get_db(),request.get_json(),hashlib.sha256(client.encode()).hexdigest(),rate,today(),current_app.secret_key)
    return jsonify(result),201 if created else 200


@shop.post('/api/shop/order-status')
def status():
    token=required_text((request.get_json() or {}).get('token'),'訂單查詢碼',100)
    row=get_db().execute('SELECT * FROM customer_orders WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row:raise Problem('找不到訂單，請使用送單成功時的私人查詢連結',status=404)
    return jsonify(order_view(get_db(),row))


@shop.post('/api/shop/recover-order')
def recover_order():
    key=required_text(request.get_json().get('request_id'),'訂單識別碼',100)
    client=session.get('shop_client')
    if not client:raise Problem('請重新整理頁面',status=403)
    client_hash=hashlib.sha256(client.encode()).hexdigest()
    conn=get_db()
    # Wait for an in-flight submission before deciding that no order was saved.
    with transaction(conn):
        row=conn.execute('SELECT * FROM customer_orders WHERE request_id=? AND client_hash=?',(key,client_hash)).fetchone()
    if not row:return jsonify(order=None)
    return jsonify(order={**order_view(get_db(),row),'token':token_for(current_app.secret_key,row['id'],key,client_hash)})


@shop.get('/shop/media/<name>')
def photo(name):
    if not re.fullmatch(r'[a-f0-9]{64}(\.thumb)?\.(jpg|jpeg|png|webp|gif)',name):raise Problem('找不到照片',status=404)
    conn=get_db()
    visible=conn.execute('SELECT 1 FROM products p JOIN shop_products s ON p.id=s.product_id WHERE s.published=1 AND p.image=?',(name,)).fetchone()
    visible=visible or conn.execute('SELECT 1 FROM recipes WHERE published=1 AND image=?',(name,)).fetchone()
    if not visible and not session.get('user'):raise Problem('找不到照片',status=404)
    path=current_app.config['DATA_DIR']/'media'/name
    if not path.is_file():raise Problem('找不到照片',status=404)
    return send_file(path)


@shop.get('/api/customer-orders')
def orders():
    conn=get_db()
    with transaction(conn):expire_orders(conn)
    rows=conn.execute('SELECT * FROM customer_orders ORDER BY created_at DESC,id DESC').fetchall()
    state=request.args.get('status','')
    if state:rows=[r for r in rows if r['status']==state]
    result=paginate(rows,request.args.get('page',1),10)
    result['items']=[order_view(conn,r,admin=True) for r in result['items']]
    return jsonify(result)


@shop.post('/api/customer-orders/<oid>/transition')
def transition(oid):
    body=request.get_json()
    return jsonify(transition_order(get_db(),oid,body.get('action'),session['user'],body.get('request_id'),today()))


@shop.get('/api/shop-admin')
def admin_data():
    conn=get_db();initialize_shop(conn)
    ps=product_map(conn,today(),include_hidden=True)
    return jsonify(products=[{**public_product(p),'published':p['published']} for p in ps.values()],
        recipes=recipe_catalog(conn,today(),admin=True),settings=settings(conn))


@shop.post('/api/shop-admin/settings')
def save_settings():
    body=request.get_json();slots=body.get('slots')
    if not isinstance(slots,list) or len(slots)>8 or not all(isinstance(s,str) and re.fullmatch(r'\d{2}:\d{2}–\d{2}:\d{2}',s) for s in slots):raise Problem('時段格式為 10:00–12:00，最多8個時段')
    for s in slots:
        start,end=s.split('–')
        if start>=end or any(int(t[:2])>23 or int(t[3:])>59 for t in (start,end)):raise Problem('取貨時段起訖時間不正確')
    enabled=body.get('enabled') is True
    if enabled and not slots:raise Problem('請先設定至少一個取貨時段')
    value={'slots':list(dict.fromkeys(slots)),'enabled':enabled}
    get_db().execute("INSERT OR REPLACE INTO metadata VALUES('shop_settings',?)",(json.dumps(value),))
    return jsonify(value)


@shop.post('/api/shop-admin/products/<int:pid>')
def publish_product(pid):
    conn=get_db()
    if not conn.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise Problem('找不到商品',status=404)
    conn.execute('INSERT OR REPLACE INTO shop_products VALUES(?,?)',(pid,int(request.get_json().get('published') is True)))
    return jsonify(ok=True)


@shop.post('/api/shop-admin/recipes')
@shop.post('/api/shop-admin/recipes/<int:rid>')
def save_recipe(rid=None):
    body=request.get_json();conn=get_db()
    name=required_text(body.get('name'),'菜名',80)
    description=str(body.get('description') or '')[:300];notes=str(body.get('notes') or '')[:600];steps=str(body.get('steps') or '')[:1200]
    theme=body.get('theme','noodles')
    if theme not in {'noodles','chicken','soup'}:raise Problem('請選擇料理圖示')
    items=body.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=20:raise Problem('料理需包含1至20項商品')
    values=[];seen=set()
    for item in items:
        if not isinstance(item,dict):raise Problem('食材格式不正確')
        pid=integer(item.get('product_id'),'商品編號',999999999);q=integer(item.get('quantity'),'販售數量')
        if pid in seen or not conn.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise Problem('食材重複或不存在')
        seen.add(pid);values.append((pid,q,int(item.get('optional') is True)))
    if all(x[2] for x in values):raise Problem('至少需要一項主食材')
    published=body.get('published') is True
    if published:
        ps=product_map(conn,today())
        if any(pid not in ps or ps[pid]['price'] is None or ps[pid]['unit'].lower() in {'kg','g','斤','公斤','公克','台斤','兩'} for pid,_,_ in values):
            raise Problem('請先上架食材並確認售價，秤重商品暫不開放料理組合')
    image=body.get('image') or None
    if image and (not re.fullmatch(r'[a-f0-9]{64}\.jpg',str(image)) or not (current_app.config['DATA_DIR']/'media'/image).is_file()):raise Problem('請先上傳有效菜色照片')
    with transaction(conn):
        if rid:
            old=conn.execute('SELECT * FROM recipes WHERE id=?',(rid,)).fetchone()
            if not old:raise Problem('找不到料理',status=404)
            if old['version']!=body.get('version'):raise Problem('料理已更新，請重新開啟',status=409)
            conn.execute('''UPDATE recipes SET name=?,description=?,theme=?,tag=?,notes=?,steps=?,published=?,image=?,version=version+1 WHERE id=?''',
                (name,description,theme,str(body.get('tag') or '')[:30],notes,steps,int(published),image,rid))
            conn.execute('DELETE FROM recipe_items WHERE recipe_id=?',(rid,))
        else:
            rid=conn.execute('''INSERT INTO recipes(slug,name,description,theme,tag,notes,steps,published,image) VALUES(?,?,?,?,?,?,?,?,?)''',
                ('custom-'+secrets.token_hex(8),name,description,theme,str(body.get('tag') or '')[:30],notes,steps,int(published),image)).lastrowid
        conn.executemany('INSERT INTO recipe_items VALUES(?,?,?,?)',[(rid,*v) for v in values])
    return jsonify(id=rid)


@shop.post('/api/shop-admin/photo')
def upload_photo():
    value=request.get_json().get('data','')
    if not isinstance(value,str) or len(value)>2800000:raise Problem('照片請小於2MB')
    try:
        raw=base64.b64decode(value,validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>16000000:raise Problem('照片尺寸太大，請先縮小')
            normalized=ImageOps.exif_transpose(im).convert('RGB');normalized.thumbnail((1200,1200))
            output=io.BytesIO();normalized.save(output,'JPEG',quality=88)
    except (ValueError,UnidentifiedImageError,OSError,Image.DecompressionBombError):raise Problem('無法讀取照片，請選擇一般 JPG 或 PNG') from None
    content=output.getvalue();name=hashlib.sha256(content).hexdigest()+'.jpg'
    (current_app.config['DATA_DIR']/'media'/name).write_bytes(content)
    return jsonify(image=name)
