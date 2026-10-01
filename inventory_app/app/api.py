import json
import re
import shutil
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file, session

from .backups import perform_backup
from .common import Problem, mutate, now, paginate, record, required_text, today, transaction
from .dashboard import get_dashboard, list_products, products_with_stock
from .db import get_db
from .exports import build_invoice_xlsx, export_state
from .imports import commit_import, preview_import
from .inventory import bulk_count_stock, count_stock, get_product, issue, receive, return_stock, reverse_movement
from .products import update_product
from .catalog_order import category_key, product_key

api = Blueprint('api', __name__)


def page_args(default=10):
    return request.args.get('page', 1), request.args.get('page_size', default)


@api.get('/')
def home():
    return render_template('index.html')


@api.get('/api/meta')
def metadata():
    conn = get_db()
    backup = conn.execute('SELECT * FROM backup_runs ORDER BY id DESC LIMIT 1').fetchone()
    return jsonify(today=today().isoformat(), categories=[r[0] for r in conn.execute('SELECT DISTINCT category FROM products ORDER BY category')],
                   catalog_categories=sorted({r['category'] for r in catalog_rows()}, key=category_key),
                   products=[dict(r) for r in conn.execute('SELECT id,code,name,unit FROM products ORDER BY name')],
                   backup=dict(backup) if backup else None, export=export_state(conn),
                   demo=current_app.config.get('DEMO', False))


@api.get('/api/dashboard')
def dashboard():
    return jsonify(get_dashboard(get_db(), today(), *page_args(6)))


@api.get('/api/products')
def products():
    return jsonify(list_products(get_db(), request.args.get('q',''), request.args.get('status',''),
                   *page_args(), today(), request.args.get('category','')))


def detail(pid):
    get_product(get_db(), pid)
    return next(p for p in products_with_stock(get_db(), today()) if p['id'] == pid)


@api.get('/api/products/<int:pid>')
def product_detail(pid):
    return jsonify(detail(pid))


@api.get('/api/products/<int:pid>/batches')
def batches(pid):
    return jsonify(paginate(detail(pid)['batches'], *page_args()))


@api.patch('/api/products/<int:pid>')
def patch_product(pid):
    body = request.get_json()
    return jsonify(update_product(get_db(), pid, body, body.get('expected_version'), session['user']))


@api.post('/api/receipts')
def receipts():
    return jsonify(receive(get_db(), request.get_json(), session['user']))


@api.post('/api/issues')
def issues():
    return jsonify(issue(get_db(), request.get_json(), session['user'], today()))


@api.post('/api/counts')
def counts():
    return jsonify(count_stock(get_db(), request.get_json(), session['user']))


@api.post('/api/counts/bulk')
def bulk_counts():
    return jsonify(bulk_count_stock(get_db(), request.get_json(), session['user']))


@api.post('/api/returns')
def returns():
    return jsonify(return_stock(get_db(), request.get_json(), session['user']))


@api.post('/api/reversals')
def reversals():
    b = request.get_json()
    return jsonify(reverse_movement(get_db(), b.get('movement_id'), b.get('reason'), b.get('request_id'), session['user']))


@api.get('/api/history')
def history():
    query = '''SELECT m.*,p.name,p.unit FROM movements m JOIN products p ON p.id=m.product_id WHERE 1=1'''
    params = []
    for field, column in [('product_id','m.product_id'), ('kind','m.kind')]:
        if request.args.get(field):
            query += f' AND {column}=?'
            params.append(request.args[field])
    for field, op in [('from','>='),('to','<=')]:
        if request.args.get(field):
            query += f' AND substr(m.created_at,1,10){op}?'
            params.append(request.args[field])
    rows = [dict(r) for r in get_db().execute(query+' ORDER BY m.id DESC', params)]
    return jsonify(paginate(rows, *page_args()))


def catalog_rows():
    conn = get_db()
    ps = {p['id']: p for p in products_with_stock(conn, today())}
    cards = [dict(r) for r in conn.execute('SELECT * FROM catalog_cards ORDER BY id')]
    for c in cards:
        p = ps.get(c['product_id'])
        c['linked'] = p is not None
        c['price'] = p['price'] if p and c['pricing_mode']=='product' else c['original_price']
        c['status'] = p['status'] if p else ('independent' if c['independent'] else 'unmapped')
        c['category'] = p['category'] if p else c['source'].split('!')[0]
        c['unit'] = p['unit'] if p else ''
    linked_ids = {c['product_id'] for c in cards if c['product_id']}
    cards += [{**p, 'id': 'product-'+str(p['id']), 'product_id': p['id'],
               'source': '', 'original_price': p['price'], 'pricing_mode': 'product', 'linked': True}
              for p in ps.values() if p['id'] not in linked_ids]
    return sorted(cards, key=product_key)


@api.get('/api/catalog')
def catalog():
    rows = catalog_rows()
    q = request.args.get('q','').casefold()
    category = request.args.get('category','')
    rows = [r for r in rows if (not q or q in (r['name']+' '+(r.get('brand') or '')).casefold()) and
            (not category or r['category']==category)]
    photo_counts = {'all':len(rows), 'present':sum(bool(r.get('image')) for r in rows)}
    photo_counts['missing'] = photo_counts['all'] - photo_counts['present']
    photos = request.args.get('photos','')
    if photos in {'present','missing'}:
        rows = [r for r in rows if bool(r.get('image')) == (photos == 'present')]
    return jsonify({**paginate(rows, *page_args(24), maximum=48), 'photo_counts':photo_counts})


@api.get('/api/mappings/<kind>')
def mappings(kind):
    if kind not in {'catalog','invoice'}:
        raise Problem('對應類型不正確')
    table = 'catalog_cards' if kind=='catalog' else 'invoice_items'
    rows = [dict(r) for r in get_db().execute(f'SELECT * FROM {table} ORDER BY id')]
    if request.args.get('pending') == '1':
        rows = [r for r in rows if not r['product_id'] and not r.get('fixed') and not r.get('independent')]
    return jsonify(paginate(rows, *page_args(5)))


@api.post('/api/mappings/<kind>/<int:mid>')
def set_mapping(kind, mid):
    if kind not in {'catalog','invoice'}:
        raise Problem('對應類型不正確')
    table = 'catalog_cards' if kind=='catalog' else 'invoice_items'
    body, conn = request.get_json(), get_db()
    with transaction(conn):
        old = conn.execute(f'SELECT * FROM {table} WHERE id=?',(mid,)).fetchone()
        if not old:
            raise Problem('找不到對應項目',status=404)
        pid = body.get('product_id') or None
        p = get_product(conn,pid) if pid else None
        if kind == 'catalog':
            mode = body.get('pricing_mode','fixed')
            if mode not in {'fixed','product'}:
                raise Problem('價格方式不正確')
            independent = int(not pid and body.get('independent') is True)
            conn.execute('UPDATE catalog_cards SET product_id=?,pricing_mode=?,independent=? WHERE id=?',
                         (pid,mode,independent,mid))
            if p and old['image']:
                conn.execute('UPDATE products SET image=?,version=version+1,updated_at=? WHERE id=?',(old['image'],now(),pid))
        else:
            if p and p['unit'] != old['unit']:
                raise Problem('販售單位不同，請選擇相同規格商品，或保留為固定發票項目')
            conn.execute('UPDATE invoice_items SET product_id=?,fixed=? WHERE id=?',
                         (pid, int(not pid and body.get('fixed') is True),mid))
        if p:
            record(conn,pid,None,'mapping','確認'+('價目表' if kind=='catalog' else '發票')+'對應',
                   str(old['product_id']),str(pid),session['user'])
    return jsonify(ok=True)


@api.post('/api/invoice-exports')
def invoice_export():
    return jsonify(build_invoice_xlsx(get_db(),current_app.config['DATA_DIR']/'exports'))


@api.post('/api/invoice-items')
def add_invoice_item():
    body, conn = request.get_json(), get_db()
    def apply():
        p = get_product(conn, body.get('product_id'))
        category = required_text(body.get('category'), '發票商品分類編號', 30)
        if not category.isascii() or not category.isdigit() or body.get('tax') not in {0, 1}:
            raise Problem('請填數字分類編號並選擇是否含稅')
        if conn.execute('SELECT 1 FROM invoice_items WHERE product_id=? OR code=?', (p['id'],p['code'])).fetchone():
            raise Problem('此商品已在發票清單內，請從商品對應查看', status=409)
        cursor = conn.execute('''INSERT INTO invoice_items(source,category,code,name,price,unit,tax,kind,product_id)
                                VALUES(?,?,?,?,?,?,?,0,?)''',
            ('product:'+str(p['id']),category,p['code'],p['name'],p['price'],p['unit'],body['tax'],p['id']))
        record(conn,p['id'],None,'mapping','新增發票商品',None,category,session['user'])
        return {'id':cursor.lastrowid}
    return jsonify(mutate(conn,body.get('request_id'),{'action':'add-invoice',**body},apply))


@api.get('/api/invoice-exports/<eid>/download')
def invoice_download(eid):
    row = get_db().execute('SELECT * FROM invoice_exports WHERE id=?',(eid,)).fetchone()
    if not row:
        raise Problem('找不到匯出檔',status=404)
    return send_file(current_app.config['DATA_DIR']/'exports'/row['filename'],as_attachment=True)


@api.post('/api/imports/preview')
def import_preview():
    source = current_app.config['SOURCE_DIR']
    paths = list(source.glob('*.xlsx'))
    if not paths:
        raise Problem('原始資料資料夾內沒有 Excel 檔案')
    return jsonify(preview_import(paths,current_app.config['DATA_DIR']/'staging'))


@api.post('/api/imports/<iid>/commit')
def import_commit(iid):
    if not re.fullmatch('[a-f0-9]{64}',iid):
        raise Problem('匯入識別碼不正確')
    data = current_app.config['DATA_DIR']
    path = data/'staging'/(iid+'.json')
    if not path.exists():
        raise Problem('請先預覽原始資料')
    preview = json.loads(path.read_text('utf-8'))
    # Stage immutable media before DB commit so committed cards never point at missing files.
    for image in (data/'staging'/'media').glob('*'):
        if image.is_file() and not (data/'media'/image.name).exists():
            shutil.copy2(image,data/'media'/image.name)
    return jsonify(commit_import(get_db(),preview,request.get_json(),session['user']))


@api.get('/media/<name>')
def media(name):
    if not session.get('user'):
        raise Problem('請先登入',status=401)
    if not re.fullmatch(r'[a-f0-9]{64}(\.thumb)?\.(jpg|jpeg|png|webp|gif)',name):
        raise Problem('找不到圖片',status=404)
    data = current_app.config['DATA_DIR']
    for folder in [data/'media',data/'staging'/'media']:
        if (folder/name).is_file():
            return send_file(folder/name)
    raise Problem('找不到圖片',status=404)


@api.post('/api/backups')
def backup():
    return jsonify(perform_backup(current_app._get_current_object()))
