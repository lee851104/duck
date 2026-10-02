"""Validate owner decisions against stable source coordinates, never snapshot IDs."""
import hashlib
import json

from tools.reconcile_sources import apply_plan


def response_plan(conn, document):
    if document.get('schema') != 'duck.owner-review.response.v2':
        raise ValueError('不支援的老闆回覆格式')
    tasks = document.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('回覆沒有確認項目')
    digest = hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    plan = {'id': 'owner-response-'+digest, 'guards': [], 'actions': []}
    seen = set()
    for task in tasks:
        source, response = task['source'], task['response']
        target, original = source['target'], source['original']
        table = target['table']
        if table not in {'catalog_cards', 'invoice_items'} or target['field'] != 'product_id':
            raise ValueError('回覆包含不支援的欄位')
        if response.get('status') != 'confirmed':
            raise ValueError('仍有未確認的老闆回覆')
        row = conn.execute(f'SELECT * FROM {table} WHERE source=?', (original['source'],)).fetchone()
        if row is None or (table, row['id']) in seen:
            raise ValueError('回覆來源不存在或重複')
        seen.add((table, row['id']))
        fields = ('name', 'brand', 'specification', 'original_price') if table == 'catalog_cards' else ('name', 'code', 'price', 'unit', 'category', 'tax', 'kind')
        if any(row[k] != original[k] for k in fields):
            raise ValueError(f'來源內容已變更，不能套用舊回覆：{original["source"]}')
        decision = response.get('decision')
        reason = '老闆確認：'+source['title']+'；回覆 '+response['choice']
        if decision == 'match':
            candidates = [p for p in source.get('candidates', []) if p['id'] == response.get('product_id')]
            if len(candidates) != 1 or response.get('choice') != f"same:{response['product_id']}":
                raise ValueError('回覆指定的商品不在原始候選清單中')
            candidate = candidates[0]
            product = conn.execute('SELECT * FROM products WHERE code=?', (candidate['code'],)).fetchone()
            if product is None or any(product[k] != candidate[k] for k in ('name', 'unit', 'category')):
                raise ValueError('候選商品的品號、名稱、分類或單位已變更')
            sources = {r[0] for r in conn.execute('SELECT source FROM batches WHERE product_id=?', (product['id'],))}
            if not candidate.get('inventory_sources') or not set(candidate['inventory_sources']) <= sources:
                raise ValueError('候選商品的庫存來源不符')
            plan['guards'].append({'table': 'products', 'id': product['id'],
                'before': {k: product[k] for k in ('code', 'name', 'unit', 'category')}})
            after = {'product_id': product['id']}
            if table == 'catalog_cards':
                after.update(independent=0, pricing_mode='product')
            else:
                after.update(fixed=0, unit=product['unit'])
        elif decision == 'independent' and response.get('choice') == 'different':
            after = {'product_id': None}
            after.update({'independent': 1, 'pricing_mode': 'fixed'} if table == 'catalog_cards' else {'fixed': 1})
        else:
            raise ValueError('無法辨識的確認結果')
        if row['product_id'] is not None or (table == 'catalog_cards' and row['independent']) or (table == 'invoice_items' and row['fixed']):
            raise ValueError('此項目已有其他對應決策，請先比對，不能直接覆寫')
        plan['actions'].append({'table': table, 'id': row['id'],
            'before': {k: row[k] for k in set(fields) | set(after) | {'source'}}, 'after': after, 'reason': reason})
    return plan


def apply_responses(conn, document):
    digest = hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    previous = conn.execute('SELECT value FROM metadata WHERE key=?', ('reconciliation:owner-response-'+digest,)).fetchone()
    if previous:
        return json.loads(previous[0])
    return apply_plan(conn, response_plan(conn, document))
