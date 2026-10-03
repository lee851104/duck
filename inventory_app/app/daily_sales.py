"""Merchant end-of-day sales sheets; every sheet is one atomic inventory change."""
import hashlib
import json
from decimal import Decimal

from .common import Problem, decimal_text, mutate, now, record, valid_date
from .inventory import get_product, quantity_for
from .line_sales import check_for_sheet
from .reservations import reserved_quantity


def sale_date(value, today):
    value = valid_date(value, False)
    if value > today.isoformat():
        raise Problem('銷售日期不能晚於今天')
    return value


def eligible_batches(conn, pid, sold_on):
    rows = conn.execute('''SELECT * FROM batches WHERE product_id=? AND quantity IS NOT NULL
        AND saleable=1 AND (expires_on IS NULL OR expires_on>=?)
        AND (received_on IS NULL OR received_on<=?)
        ORDER BY expires_on IS NULL,expires_on,received_on,id''', (pid, sold_on, sold_on))
    for row in rows:
        batch = dict(row)
        batch['available'] = max(Decimal(0), Decimal(row['quantity']) - reserved_quantity(conn, row['id']))
        yield batch


def plan_sheet(conn, command, today):
    sold_on = sale_date(command.get('sold_on'), today)
    note = command.get('note', '')
    if not isinstance(note, str) or len(note) > 500:
        raise Problem('備註最多 500 字')
    items = command.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise Problem('請加入 1 至 200 項商品')
    if conn.execute("SELECT 1 FROM daily_sales WHERE sold_on=? AND status='posted'", (sold_on,)).fetchone():
        raise Problem('這一天已有銷售單，請先查看紀錄；要重填請先沖銷原單', status=409)
    seen, lines = set(), []
    for item in items:
        if not isinstance(item, dict) or type(item.get('product_id')) is not int:
            raise Problem('商品格式不正確')
        pid = item['product_id']
        if pid in seen:
            raise Problem('同一商品請合併數量，只填一列')
        seen.add(pid)
        p = get_product(conn, pid)
        try:
            qty = quantity_for(p, item.get('quantity'), True)
            batches = list(eligible_batches(conn, pid, sold_on))
            available = sum((b['available'] for b in batches), Decimal(0))
            if qty > available:
                raise Problem(f"可扣庫存只有 {decimal_text(available)} {p['unit']}，請先確認盤點、效期與可售狀態", status=409)
            left, allocations = qty, []
            for b in batches:
                take = min(left, b['available'])
                if take <= 0:
                    continue
                allocations.append({'batch_id': b['id'], 'version': b['version'],
                    'expires_on': b['expires_on'], 'quantity': decimal_text(take),
                    'before': b['quantity'], 'after': decimal_text(Decimal(b['quantity']) - take)})
                left -= take
                if left == 0:
                    break
            lines.append({'product_id': pid, 'name': p['name'], 'code': p['code'], 'unit': p['unit'],
                'quantity': decimal_text(qty), 'available': decimal_text(available),
                'remaining': decimal_text(available - qty), 'allocations': allocations})
        except Problem as error:
            raise Problem(f"{p['name']}：{error.message}", status=error.status, fields={'product_id': pid}) from None
    # 帶入的 LINE 訂單也算進確認碼：換了訂單就要重新預覽。
    result = {'sold_on': sold_on, 'note': note.strip(), 'items': lines,
              'line_orders': check_for_sheet(conn, command.get('line_orders'))}
    result['revision'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def post_sheet(conn, command, actor, today):
    def apply():
        plan = plan_sheet(conn, command, today)
        if command.get('revision') != plan['revision']:
            raise Problem('庫存或內容已變動，請重新預覽再確認扣庫存', status=409)
        sid = conn.execute('''INSERT INTO daily_sales(sold_on,note,status,created_at,actor)
            VALUES(?,?,'posted',?,?)''', (plan['sold_on'], plan['note'], now(), str(actor))).lastrowid
        for line in plan['items']:
            lid = conn.execute('''INSERT INTO daily_sale_lines(sheet_id,product_id,name,code,unit,quantity)
                VALUES(?,?,?,?,?,?)''', (sid, line['product_id'], line['name'], line['code'], line['unit'], line['quantity'])).lastrowid
            for a in line['allocations']:
                conn.execute('UPDATE batches SET quantity=?,version=version+1 WHERE id=?', (a['after'], a['batch_id']))
                mid = record(conn, line['product_id'], a['batch_id'], 'issue',
                    f"每日銷售單 #{sid} · {plan['sold_on']}", a['before'], a['after'], actor)
                conn.execute('INSERT INTO daily_sale_movements(line_id,movement_id) VALUES(?,?)', (lid, mid))
        for oid in plan['line_orders']:
            conn.execute('INSERT INTO line_order_sales(order_id,sheet_id,created_at) VALUES(?,?,?)', (oid, sid, now()))
        return sheet_detail(conn, sid)
    return mutate(conn, command.get('request_id'), {'kind': 'daily_sale', **command}, apply)


def sheet_detail(conn, sid):
    row = conn.execute('SELECT * FROM daily_sales WHERE id=?', (sid,)).fetchone()
    if not row:
        raise Problem('找不到銷售單', status=404)
    result = dict(row)
    result['items'] = []
    for row in conn.execute('SELECT * FROM daily_sale_lines WHERE sheet_id=? ORDER BY id', (sid,)):
        line = dict(row)
        line['allocations'] = [dict(m) for m in conn.execute('''SELECT m.id AS movement_id,m.batch_id,
            m.before_value,m.after_value FROM movements m JOIN daily_sale_movements d ON d.movement_id=m.id
            WHERE d.line_id=? ORDER BY m.id''', (line['id'],))]
        result['items'].append(line)
    result['line_orders'] = [dict(r) for r in conn.execute('''SELECT o.id,o.sent_on,o.sent_at,o.location,o.customer
        FROM line_order_sales s JOIN line_orders o ON o.id=s.order_id WHERE s.sheet_id=?
        ORDER BY o.sent_on,o.sent_at,o.id''', (sid,))]
    return result


def void_sheet(conn, sid, command, actor):
    from .common import required_text
    reason = required_text(command.get('reason'), '沖銷原因', 200)

    def apply():
        sheet = sheet_detail(conn, sid)
        if sheet['status'] != 'posted':
            raise Problem('這張銷售單已沖銷', status=409)
        for line in sheet['items']:
            for a in line['allocations']:
                b = conn.execute('SELECT * FROM batches WHERE id=?', (a['batch_id'],)).fetchone()
                if b['quantity'] is None or conn.execute(
                    "SELECT 1 FROM movements WHERE batch_id=? AND kind='count' AND id>?",
                    (b['id'], a['movement_id'])).fetchone():
                    raise Problem('這張單的商品已有後續盤點，請以新的盤點更正，避免重複加回庫存', status=409)
                after = Decimal(b['quantity']) + Decimal(a['before_value']) - Decimal(a['after_value'])
                conn.execute('UPDATE batches SET quantity=?,version=version+1 WHERE id=?', (decimal_text(after), b['id']))
                record(conn, line['product_id'], b['id'], 'reverse', f'沖銷每日銷售單 #{sid}：{reason}',
                    b['quantity'], decimal_text(after), actor, a['movement_id'])
        conn.execute("UPDATE daily_sales SET status='void',void_reason=?,voided_at=? WHERE id=?", (reason, now(), sid))
        return sheet_detail(conn, sid)
    return mutate(conn, command.get('request_id'), {'kind': 'void_daily_sale', 'sheet_id': sid, **command}, apply)
