from decimal import Decimal

from .common import (Problem, decimal_text, mutate, now, number, record,
                     required_text, valid_date)
from .reservations import protect_reserved


def get_product(conn, pid):
    row = conn.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone()
    if not row:
        raise Problem('找不到商品', status=404)
    return dict(row)


def quantity_for(product, value, positive=False):
    quantity = number(value, positive=positive)
    if product['unit'].lower() not in {'kg', 'g', '斤', '公斤', '公克', '台斤', '兩'} and quantity != quantity.to_integral():
        raise Problem('這項商品以整數件數管理；重量商品才可填小數')
    return quantity


def receive(conn, command, actor_id, kind='receive'):
    def apply():
        p = get_product(conn, command.get('product_id'))
        qty = quantity_for(p, command.get('quantity'), True)
        cost = number(command.get('cost'), '進價', optional=True)
        received = valid_date(command.get('received_on'), False)
        expiry = valid_date(command.get('expires_on'))
        if expiry is None and not command.get('unknown_expiry'):
            raise Problem('請填效期，或勾選效期未知')
        saleable = kind != 'return' and (bool(expiry) or command.get('saleable_confirmed') is True)
        cur = conn.execute('''INSERT INTO batches
            (product_id,quantity,cost,received_on,expires_on,saleable) VALUES(?,?,?,?,?,?)''',
            (p['id'], decimal_text(qty), decimal_text(cost), received, expiry, int(saleable)))
        bid = cur.lastrowid
        mid = record(conn, p['id'], bid, kind, '顧客退回（待確認）' if kind == 'return' else '進貨',
                     '0', decimal_text(qty), actor_id)
        return {'batch_id': bid, 'movement_ids': [mid]}
    return mutate(conn, command.get('request_id'), {'kind': kind, **command}, apply)


def return_stock(conn, command, actor_id):
    return receive(conn, {**command, 'unknown_expiry': not command.get('expires_on')}, actor_id, 'return')


def checked_batch(conn, bid, expected_version):
    batch = conn.execute('SELECT * FROM batches WHERE id=?', (bid,)).fetchone()
    if not batch:
        raise Problem('找不到批次', status=404)
    if batch['version'] != expected_version:
        raise Problem('庫存已被更新，請重新開啟商品後再操作', status=409)
    return dict(batch)


def issue(conn, command, actor_id, today):
    def apply():
        p = get_product(conn, command.get('product_id'))
        reason = command.get('reason')
        if reason not in {'銷售', '報廢', '退供應商'}:
            raise Problem('請選擇有效的出貨原因')
        allocations = command.get('allocations')
        if not isinstance(allocations, list) or not allocations or len(allocations) > 500:
            raise Problem('請選擇實際出貨批次')
        seen, mids = set(), []
        total = Decimal(0)
        for a in allocations:
            if not isinstance(a, dict):
                raise Problem('批次格式不正確')
            b = checked_batch(conn, a.get('batch_id'), a.get('expected_version'))
            if b['product_id'] != p['id'] or b['id'] in seen:
                raise Problem('批次商品不符或重複')
            seen.add(b['id'])
            qty = quantity_for(p, a.get('quantity'), True)
            total += qty
            if b['quantity'] is None:
                raise Problem('這批尚未盤點，請先填寫實際庫存')
            if reason == '銷售' and (not b['saleable'] or (b['expires_on'] and b['expires_on'] < today.isoformat())):
                raise Problem('過期或未確認可售的批次不能銷售')
            remaining = Decimal(b['quantity']) - qty
            if remaining < 0:
                raise Problem('出貨數量超過這批庫存', status=409)
            protect_reserved(conn,b['id'],remaining)
            conn.execute('UPDATE batches SET quantity=?,version=version+1 WHERE id=?',
                         (decimal_text(remaining), b['id']))
            mids.append(record(conn, p['id'], b['id'], 'issue', reason, b['quantity'],
                               decimal_text(remaining), actor_id))
        if command.get('expected_total') not in (None, '') and total != quantity_for(p, command['expected_total'], True):
            raise Problem('各批分配數量與預計出貨總數不一致，請調整後再確認')
        return {'movement_ids': mids}
    return mutate(conn, command.get('request_id'), {'kind': 'issue', **command}, apply)


def _apply_count_stock(conn, command, actor_id):
    b = checked_batch(conn, command.get('batch_id'), command.get('expected_version'))
    p = get_product(conn, b['product_id'])
    qty = quantity_for(p, command.get('actual_quantity'))
    expiry = valid_date(command['expires_on']) if 'expires_on' in command else b['expires_on']
    saleable = b['saleable']
    if 'saleable_confirmed' in command:
        saleable = int(command['saleable_confirmed'] is True)
    protect_reserved(conn,b['id'],qty,expiry,saleable)
    conn.execute('UPDATE batches SET quantity=?,expires_on=?,saleable=?,version=version+1 WHERE id=?',
                 (decimal_text(qty), expiry, saleable, b['id']))
    reason = '盤點調整'
    if int(saleable) != int(b['saleable']):
        reason += '・確認可售' if saleable else '・改為不可售'
    mid = record(conn, p['id'], b['id'], 'count', reason, b['quantity'], decimal_text(qty), actor_id)
    return {'batch_id': b['id'], 'movement_ids': [mid]}


def count_stock(conn, command, actor_id):
    return mutate(conn, command.get('request_id'), {'kind': 'count', **command},
                  lambda: _apply_count_stock(conn, command, actor_id))


def bulk_count_stock(conn, command, actor_id):
    items = command.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise Problem('請填入 1 至 200 筆盤點數量')
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise Problem('盤點列格式不正確')
        bid = item.get('batch_id')
        if type(bid) is not int or bid < 1 or bid in seen:
            raise Problem('盤點批次無效或重複')
        seen.add(bid)
        # 集中盤點可以順便確認可售（效期未知也可以），但不在這裡改效期或改成不可售。
        if set(item) - {'batch_id', 'actual_quantity', 'expected_version', 'saleable_confirmed'} or (
                'saleable_confirmed' in item and item['saleable_confirmed'] is not True):
            raise Problem('集中盤點只調整數量或確認可售，其他資料請至商品明細修改')

    def apply():
        results = []
        for item in items:
            try:
                results.append(_apply_count_stock(conn, item, actor_id))
            except Problem as error:
                raise Problem(error.message, code=error.code, status=error.status,
                              fields={**error.fields, 'batch_id': item['batch_id']}) from None
        return {'results': results, 'movement_ids': [mid for row in results for mid in row['movement_ids']]}

    return mutate(conn, command.get('request_id'), {'kind': 'bulk_count', **command}, apply)


def reverse_movement(conn, movement_id, reason, request_id, actor_id):
    reason = required_text(reason, '更正原因')

    def apply():
        m = conn.execute('SELECT * FROM movements WHERE id=?', (movement_id,)).fetchone()
        if not m or m['kind'] not in {'receive', 'issue', 'return'}:
            raise Problem('此紀錄請以盤點或重新修改商品更正')
        if m['reason'].startswith('客人訂單 '):
            raise Problem('訂單取貨紀錄不能直接沖銷，退貨請使用「顧客退回」登記', status=409)
        if conn.execute('SELECT 1 FROM daily_sale_movements WHERE movement_id=?', (movement_id,)).fetchone():
            raise Problem('請到每日銷售單紀錄沖銷整張單，避免單據與庫存不一致', status=409)
        if conn.execute('SELECT 1 FROM movements WHERE reversal_of=?', (movement_id,)).fetchone():
            raise Problem('這筆紀錄已沖銷', status=409)
        b = conn.execute('SELECT * FROM batches WHERE id=?', (m['batch_id'],)).fetchone()
        if b['quantity'] is None:
            raise Problem('批次尚未盤點')
        change = Decimal(m['after_value']) - Decimal(m['before_value'])
        after = Decimal(b['quantity']) - change
        if after < 0:
            raise Problem('這批已出貨，不能直接沖銷進貨', status=409)
        protect_reserved(conn,b['id'],after)
        # An intervening count supersedes previous physical balance assumptions.
        if conn.execute("SELECT 1 FROM movements WHERE batch_id=? AND kind='count' AND id>?",
                        (b['id'], movement_id)).fetchone():
            raise Problem('這批已有後續盤點，請以新的盤點更正', status=409)
        conn.execute('UPDATE batches SET quantity=?,version=version+1 WHERE id=?', (decimal_text(after), b['id']))
        mid = record(conn, m['product_id'], b['id'], 'reverse', reason, b['quantity'], decimal_text(after), actor_id, movement_id)
        return {'movement_ids': [mid]}
    return mutate(conn, request_id, {'kind': 'reverse', 'id': movement_id, 'reason': reason}, apply)
