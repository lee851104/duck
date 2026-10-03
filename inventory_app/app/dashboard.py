import json
from datetime import date
from decimal import Decimal

from .common import decimal_text, now, paginate
from .catalog_order import product_key


def products_with_stock(conn, today):
    reserved = {}
    for row in conn.execute('''SELECT r.batch_id,r.quantity FROM reservations r
        JOIN customer_orders o ON o.id=r.order_id
        WHERE o.status IN ('confirmed','ready') AND o.hold_until>=?''', (now(),)):
        reserved[row['batch_id']] = reserved.get(row['batch_id'], Decimal(0)) + Decimal(row['quantity'])
    batches = {}
    for row in conn.execute('SELECT * FROM batches ORDER BY expires_on IS NULL,expires_on,id'):
        b = dict(row)
        b['reserved_quantity'] = decimal_text(reserved.get(b['id'], Decimal(0)))
        b['expired'] = bool(b['expires_on'] and b['expires_on'] < today.isoformat())
        b['days_left'] = (date.fromisoformat(b['expires_on']) - today).days if b['expires_on'] else None
        batches.setdefault(b['product_id'], []).append(b)
    items = []
    for row in conn.execute('SELECT * FROM products ORDER BY category,code,id'):
        p = dict(row)
        bs = batches.get(p['id'], [])
        unknown = not bs or any(b['quantity'] is None for b in bs)
        saleable = [b for b in bs if not b['expired'] and b['saleable'] and b['quantity'] is not None]
        quantity = sum((max(Decimal(0),Decimal(b['quantity'])-Decimal(b['reserved_quantity'])) for b in saleable), Decimal(0))
        p['reserved_quantity'] = decimal_text(sum((Decimal(b['reserved_quantity']) for b in bs),Decimal(0)))
        p['quantity'] = None if unknown else decimal_text(quantity)
        p['known_quantity'] = decimal_text(quantity)
        p['uncounted'] = unknown
        p['expired'] = [b for b in bs if b['expired'] and (b['quantity'] is None or Decimal(b['quantity']) > 0)]
        p['expiring'] = [b for b in saleable if b['days_left'] is not None and 0 <= b['days_left'] <= 30 and Decimal(b['quantity']) > 0]
        p['nearest_expiry'] = min((b['expires_on'] for b in saleable if b['expires_on'] and Decimal(b['quantity']) > 0), default=None)
        # 已盤點、還沒確認可售的庫存：不能賣，但也不是缺貨，避免老闆誤以為要補貨。
        unconfirmed = sum((Decimal(b['quantity']) for b in bs
                           if not b['expired'] and not b['saleable'] and b['quantity'] is not None), Decimal(0))
        p['unconfirmed_quantity'] = decimal_text(unconfirmed)
        p['status'] = 'uncounted' if unknown else ('unconfirmed' if quantity == 0 and unconfirmed > 0 else
                       'out' if quantity == 0 else
                       'low' if p['minimum'] is not None and quantity < Decimal(p['minimum']) else 'normal')
        p['conversions'] = json.loads(p['conversions'])
        p['batches'] = bs
        items.append(p)
    return sorted(items, key=product_key)


def list_products(conn, query='', status='', page=1, page_size=10, today=None, category=''):
    items = products_with_stock(conn, today or date.today())
    categories = {value for value in ([category] if isinstance(category, str) else category) if value}
    statuses = {value for value in ([status] if isinstance(status, str) else status) if value}

    def matches_status(p, value):
        if value in {'expiring', 'expired'}:
            return bool(p[value])
        if value == 'restock':
            return p['status'] in {'out', 'low'}
        return p['status'] == value

    def match(p):
        if query and query.casefold() not in (p['code'] + ' ' + p['name']).casefold():
            return False
        if categories and p['category'] not in categories:
            return False
        return not statuses or any(matches_status(p, value) for value in statuses)
    return paginate([p for p in items if match(p)], page, page_size, maximum=24)


def get_dashboard(conn, today, page=1, page_size=6):
    products = products_with_stock(conn, today)
    alerts = []
    for p in products:
        for b in p['expired']:
            alerts.append({'product_id': p['id'], 'name': p['name'], 'status': 'expired',
                           'batch_id': b['id'], 'detail': b['expires_on'] + ' 到期',
                           'quantity': b['quantity'], 'unit': p['unit']})
        if p['status'] in {'out', 'low'}:
            alerts.append({'product_id': p['id'], 'name': p['name'], 'status': p['status'],
                           'detail': '需補貨', 'quantity': p['quantity'], 'unit': p['unit']})
        if p['status'] == 'unconfirmed':
            alerts.append({'product_id': p['id'], 'name': p['name'], 'status': 'unconfirmed',
                           'detail': '已盤點，待確認可售', 'quantity': p['unconfirmed_quantity'], 'unit': p['unit']})
        for b in p['expiring']:
            alerts.append({'product_id': p['id'], 'name': p['name'], 'status': 'expiring',
                           'batch_id': b['id'], 'detail': '今日到期' if b['days_left'] == 0 else f"{b['days_left']} 天後到期",
                           'quantity': b['quantity'], 'unit': p['unit']})
    order = {'expired': 0, 'out': 1, 'unconfirmed': 2, 'expiring': 3, 'low': 4}
    alerts.sort(key=lambda a: (order[a['status']], a['name']))
    latest = conn.execute('SELECT MAX(created_at) FROM movements').fetchone()[0]
    return {'out_of_stock_products': sum(p['status'] == 'out' for p in products),
            'low_stock_products': sum(p['status'] == 'low' for p in products),
            'uncounted_products': sum(p['uncounted'] for p in products),
            'expiring_batches': sum(len(p['expiring']) for p in products),
            'expired_batches': sum(len(p['expired']) for p in products),
            'total_products': len(products), 'updated_at': latest,
            'alerts': paginate(alerts, page, page_size, 6)}
