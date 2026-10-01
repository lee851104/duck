import json
import sqlite3

from .common import (Problem, decimal_text, now, number, record,
                     required_text, transaction)


def product_values(values):
    unit = required_text(values.get('unit'), '單位', 20)
    conversions = values.get('conversions', {})
    if not isinstance(conversions, dict):
        raise Problem('包裝換算格式不正確')
    conversions = {required_text(k, '包裝單位', 20): decimal_text(number(v, '換算數量', positive=True))
                   for k, v in conversions.items()}
    return {'code': required_text(values.get('code'), '品號', 60),
            'name': required_text(values.get('name'), '品名'), 'unit': unit,
            'category': str(values.get('category') or '')[:100],
            'supplier': str(values.get('supplier') or '')[:100],
            'price': decimal_text(number(values.get('price'), '售價', optional=True)),
            'minimum': decimal_text(number(values.get('minimum'), '最低庫存', optional=True)),
            'specification': str(values.get('specification') or '')[:200],
            'conversions': json.dumps(conversions, ensure_ascii=False)}


def create_product(conn, values, actor_id):
    v = product_values(values)
    with transaction(conn):
        try:
            cur = conn.execute('''INSERT INTO products
                (code,name,category,supplier,unit,price,minimum,specification,conversions,created_at,updated_at)
                VALUES(:code,:name,:category,:supplier,:unit,:price,:minimum,:specification,:conversions,:at,:at)''',
                {**v, 'at': now()})
        except sqlite3.IntegrityError:
            raise Problem('品號已被使用，請換一個品號', status=409) from None
        pid = cur.lastrowid
        conn.execute('INSERT INTO batches(product_id,quantity,source) VALUES(?,NULL,?)', (pid, '初始待盤點'))
        record(conn, pid, None, 'create', '新增商品', None, v['name'], actor_id)
    return dict(conn.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone())


def update_product(conn, product_id, values, expected_version, actor_id):
    with transaction(conn):
        old = conn.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchone()
        if not old:
            raise Problem('找不到商品', status=404)
        if old['version'] != expected_version:
            raise Problem('商品已被修改，請重新開啟', status=409)
        previous = dict(old)
        previous['conversions'] = json.loads(old['conversions'])
        v = product_values({**previous, **values})
        if v['unit'] != old['unit']:
            raise Problem('已有批次的基本單位不能直接修改，請建立新規格商品')
        try:
            conn.execute('''UPDATE products SET code=:code,name=:name,category=:category,
                supplier=:supplier,price=:price,minimum=:minimum,specification=:specification,
                conversions=:conversions,version=version+1,updated_at=:at WHERE id=:id''',
                {**v, 'id': product_id, 'at': now()})
        except sqlite3.IntegrityError:
            raise Problem('品號已被使用', status=409) from None
        if v['price'] != old['price']:
            record(conn, product_id, None, 'price', '修改售價', old['price'], v['price'], actor_id)
        else:
            record(conn, product_id, None, 'edit', '修改商品資料',
                   json.dumps(previous, ensure_ascii=False), json.dumps(v, ensure_ascii=False), actor_id)
    return dict(conn.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchone())
