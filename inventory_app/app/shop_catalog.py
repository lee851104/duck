import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal

from .common import Problem, decimal_text, number, required_text, transaction
from .dashboard import products_with_stock
from .reservations import reserved_quantity


SEEDS = [
 ('tomato-noodles','番茄牛肉烏龍麵','濃郁番茄牛肉湯，搭配滑順烏龍麵。','🍜','noodles','快速上桌',
  '按整包販售，烏龍麵內含份數請依包裝。自備飲用水；圖片為料理示意。',
  '依湯包標示加熱。\n烏龍麵依包裝指示煮熟。\n合在碗中，依喜好調整湯量。',
  [('C19002',1,0),('C15001',1,0)]),
 ('teriyaki-chicken','照燒雞腿','鹹甜醬香的雞腿，今晚的下飯主菜。','🍗','chicken','下飯主菜',
  '醬油、味醂按整瓶販售，可取消家裡已有的。自備少量食用油與水，白飯不包含。',
  '雞腿依實際厚度充分煎熟。\n取適量醬油、味醂和水調成醬汁。\n加入鍋中拌煮收汁；只使用所需調味量。',
  [('B10006',1,0),('F07001',1,1),('F07003',1,1)]),
 ('corn-meatball-soup','玉米貢丸湯','甜玉米配上彈牙貢丸，一鍋暖暖上桌。','🍲','soup','暖心湯品',
  '貢丸、玉米按整包／整罐販售；雞湯塊按整盒，可取消家裡已有的。自備飲用水。',
  '依雞湯塊包裝比例，取所需份量加入水中。\n放入貢丸，依包裝指示煮熟。\n加入適量玉米粒煮熱，剩餘原料留待下次使用。',
  [('J03001',1,0),('D15003',1,0),('H99004',1,1)])
]
WEIGHT_UNITS={'kg','g','斤','公斤','公克','台斤','兩'}


def initialize_shop(conn, publish_existing=None):
    if publish_existing is None:
        publish_existing=not conn.execute("SELECT 1 FROM metadata WHERE key='shop_initialized'").fetchone()
    with transaction(conn):
        conn.execute('INSERT OR IGNORE INTO shop_products SELECT id,? FROM products',(int(publish_existing),))
        conn.execute("INSERT OR IGNORE INTO metadata VALUES('shop_initialized','1')")
        conn.execute("INSERT OR IGNORE INTO metadata VALUES('shop_settings',?)",(json.dumps({'slots':[],'enabled':False}),))
        for slug,name,description,icon,theme,tag,notes,steps,items in SEEDS:
            if conn.execute('SELECT 1 FROM recipes WHERE slug=?',(slug,)).fetchone():
                continue
            products={r['code']:r['id'] for r in conn.execute('SELECT id,code FROM products')}
            if any(code not in products for code,_,_ in items):
                continue
            rid=conn.execute('''INSERT INTO recipes(slug,name,description,icon,theme,tag,notes,steps,published)
                VALUES(?,?,?,?,?,?,?,?,1)''',(slug,name,description,icon,theme,tag,notes,steps)).lastrowid
            conn.executemany('INSERT INTO recipe_items VALUES(?,?,?,?)',[(rid,products[c],q,o) for c,q,o in items])


def settings(conn):
    row=conn.execute("SELECT value FROM metadata WHERE key='shop_settings'").fetchone()
    return json.loads(row[0]) if row else {'slots':[],'enabled':False}


def product_map(conn, day, include_hidden=False):
    published={r['product_id']:bool(r['published']) for r in conn.execute('SELECT * FROM shop_products')}
    result={}
    for p in products_with_stock(conn,day):
        if not include_hidden and not published.get(p['id']):
            continue
        # Customer orders require known dated stock; no guessed expiry.
        available=sum((max(Decimal(0),Decimal(b['quantity'])-reserved_quantity(conn,b['id']))
            for b in p['batches'] if b['quantity'] is not None and b['saleable'] and b['expires_on'] and not b['expired']),Decimal(0))
        status='pending' if p['uncounted'] or p['price'] is None or p['unit'].lower() in WEIGHT_UNITS else 'available' if available>0 else 'sold_out'
        result[p['id']]={'id':p['id'],'name':p['name'],'category':re.sub(r'^[A-Z]','',p['category']),
            'unit':p['unit'],'pack':p['specification'] or '1'+p['unit'],'price':p['price'],
            'image':p['image'],'status':status,'published':published.get(p['id'],False),
            '_quantity':available,'_code':p['code']}
    return result


def public_product(p):
    return {k:v for k,v in p.items() if not k.startswith('_') and k!='published'}


def recipe_catalog(conn, day, admin=False):
    products=product_map(conn,day,include_hidden=admin)
    rows=[]
    for r in conn.execute('SELECT * FROM recipes '+('' if admin else 'WHERE published=1 ')+'ORDER BY id'):
        item=dict(r);components=[];total=Decimal(0);valid=True;available=True
        for x in conn.execute('SELECT * FROM recipe_items WHERE recipe_id=? ORDER BY optional,product_id',(r['id'],)):
            p=products.get(x['product_id'])
            if p is None:
                valid=False;continue
            components.append({**public_product(p),'quantity':x['quantity'],'optional':bool(x['optional'])})
            if p['price'] is None:valid=False
            else:total+=Decimal(p['price'])*x['quantity']
            if p['status']!='available' or p['_quantity']<x['quantity']:available=False
        item.update(items=components,total=decimal_text(total) if valid and components else None,
                    available=bool(valid and components and available),complete=valid and bool(components))
        rows.append(item)
    return rows


def integer(value, label, maximum=99):
    if isinstance(value,bool):raise Problem(label+'必須為整數')
    n=number(value,label,positive=True)
    if n!=n.to_integral() or n>maximum:raise Problem(label+f'必須是1至{maximum}的整數')
    return int(n)


def quote(conn, selection, day):
    if not isinstance(selection,dict):raise Problem('購物車格式不正確')
    singles,recipes=selection.get('items',[]),selection.get('recipes',[])
    if not isinstance(singles,list) or not isinstance(recipes,list) or len(singles)+len(recipes)>60:
        raise Problem('購物車項目過多或格式不正確')
    ps=product_map(conn,day);amounts=defaultdict(int);groups=[]
    for s in singles:
        if not isinstance(s,dict):raise Problem('商品格式不正確')
        pid=integer(s.get('product_id'),'商品編號',999999999);q=integer(s.get('quantity'),'購買數量')
        amounts[pid]+=q;groups.append({'name':'單買商品','items':[{'product_id':pid,'quantity':q}]})
    for selection in recipes:
        if not isinstance(selection,dict):raise Problem('料理格式不正確')
        rid=integer(selection.get('recipe_id'),'料理編號',999999999);q=integer(selection.get('quantity'),'組合數量')
        r=conn.execute('SELECT * FROM recipes WHERE id=? AND published=1',(rid,)).fetchone()
        if not r:raise Problem('料理已下架，請重新選購')
        omit=selection.get('omit',[])
        if not isinstance(omit,list) or len(omit)>50:raise Problem('調味料格式不正確')
        omit={integer(pid,'調味料編號',999999999) for pid in omit}
        components=conn.execute('SELECT * FROM recipe_items WHERE recipe_id=?',(rid,)).fetchall()
        if not components or not omit.issubset({x['product_id'] for x in components if x['optional']}):
            raise Problem('只能取消此料理內的調味料')
        parts=[]
        for x in components:
            if x['product_id'] in omit:continue
            quantity=x['quantity']*q;amounts[x['product_id']]+=quantity
            parts.append({'product_id':x['product_id'],'quantity':quantity})
        groups.append({'name':r['name'],'quantity':q,'items':parts})
    if not amounts:raise Problem('購物車還沒有商品')
    rows=[];total=Decimal(0);issues=[]
    for pid,quantity in sorted(amounts.items()):
        p=ps.get(pid)
        if not p:raise Problem('商品已下架或尚未開放，請重新選購')
        if quantity>99:raise Problem('同項商品一次最多99個販售單位')
        if p['price'] is None:raise Problem(p['name']+'尚未確認售價')
        subtotal=Decimal(p['price'])*quantity;total+=subtotal
        rows.append({**public_product(p),'quantity':str(quantity),'subtotal':decimal_text(subtotal)})
        if p['status']!='available' or p['_quantity']<quantity:issues.append(p['name']+'：目前庫存不足或待店家確認')
    content={'items':rows,'groups':groups,'total':decimal_text(total)}
    # Stock changes are validated separately; price/name/quantity changes require re-confirming.
    basis=[{k:r[k] for k in ('id','name','unit','pack','price','quantity')} for r in rows]
    content.update(revision=hashlib.sha256(json.dumps([basis,groups],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),issues=issues)
    return content
