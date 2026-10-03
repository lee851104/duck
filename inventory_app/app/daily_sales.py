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


def _with_available(conn, rows):
    for row in rows:
        batch = dict(row)
        batch['available'] = max(Decimal(0), Decimal(row['quantity']) - reserved_quantity(conn, row['id']))
        yield batch


def eligible_batches(conn, pid, sold_on):
    return _with_available(conn, conn.execute('''SELECT * FROM batches WHERE product_id=? AND quantity IS NOT NULL
        AND saleable=1 AND (expires_on IS NULL OR expires_on>=?)
        AND (received_on IS NULL OR received_on<=?)
        ORDER BY expires_on IS NULL,expires_on,received_on,id''', (pid, sold_on, sold_on)))


def later_batches(conn, pid, sold_on, today):
    """補登用：銷售日之後才進貨、今天以前已到的可售批次。

    較晚日期的銷售單先送出時，會依效期先扣掉舊批次；補登較早日期時，不足的部分改從這些批次扣，總數仍正確。
    """
    return _with_available(conn, conn.execute('''SELECT * FROM batches WHERE product_id=? AND quantity IS NOT NULL
        AND saleable=1 AND (expires_on IS NULL OR expires_on>=?)
        AND received_on>? AND received_on<=?
        ORDER BY expires_on IS NULL,expires_on,received_on,id''', (pid, sold_on, sold_on, today)))


def short_time(stamp):
    return stamp[5:10].replace('-', '/') + ' ' + stamp[11:16]


def sale_warnings(conn, p, sold_on, qty, available, allocations, backfill):
    """送出前要老闆確認的情況；提醒也算進確認碼，內容變了就要重新預覽。"""
    found, name, unit = [], p['name'], p['unit']
    moved = sum((Decimal(a['quantity']) for a in allocations if a.get('later')), Decimal(0))
    if moved:
        found.append(('later_stock', f'{name}：{sold_on} 當天已有的批次只剩 {decimal_text(available)} {unit}，'
                      f'其餘 {decimal_text(moved)} {unit} 改從之後進貨的批次扣（較晚日期的銷售單先送出時會這樣）。'
                      '請確認數量沒有填錯。'))
    if backfill:
        # 盤點是當下的實際數量；補登前一天的銷售時，盤點數字通常已經扣掉這天賣出的量。
        counted = []
        for a in allocations:
            stamp = conn.execute("""SELECT MAX(created_at) FROM movements WHERE batch_id=? AND kind='count'
                AND substr(created_at,1,10)>=?""", (a['batch_id'], sold_on)).fetchone()[0]
            if stamp:
                counted.append(f"#{a['batch_id']}（{short_time(stamp)}）")
        if counted:
            found.append(('counted', f"{name}：批次 {'、'.join(counted)}在 {sold_on} 當天或之後盤點過。"
                          '盤點數量如果已經扣掉這天賣出的量，再扣會重複，請把這項移出這張單；'
                          '只有盤點時還沒扣掉這天的量，才勾選確認。'))
    manual = sum((Decimal(r['before_value']) - Decimal(r['after_value']) for r in conn.execute(
        """SELECT m.before_value,m.after_value FROM movements m WHERE m.product_id=? AND m.kind='issue'
        AND m.reason='銷售' AND substr(m.created_at,1,10)=?
        AND NOT EXISTS (SELECT 1 FROM movements r WHERE r.reversal_of=m.id)""", (p['id'], sold_on))), Decimal(0))
    if manual:
        found.append(('manual_sale', f'{name}：{sold_on} 已用「店內賣出」記錄 {decimal_text(manual)} {unit}。'
                      f'如果這張單填的 {decimal_text(qty)} {unit} 已包含這些，請先扣掉再送出，避免重複扣庫存。'))
    return [{'product_id': p['id'], 'kind': kind, 'message': message} for kind, message in found]


def plan_sheet(conn, command, today):
    sold_on = sale_date(command.get('sold_on'), today)
    backfill = sold_on < today.isoformat()
    note = command.get('note', '')
    if not isinstance(note, str) or len(note) > 500:
        raise Problem('備註最多 500 字')
    items = command.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise Problem('請加入 1 至 200 項商品')
    if conn.execute("SELECT 1 FROM daily_sales WHERE sold_on=? AND status='posted'", (sold_on,)).fetchone():
        raise Problem('這一天已有銷售單，請先查看紀錄；要重填請先沖銷原單', status=409)
    seen, lines, warnings = set(), [], []
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
            later = list(later_batches(conn, pid, sold_on, today.isoformat())) if backfill and qty > available else []
            extra = sum((b['available'] for b in later), Decimal(0))
            if qty > available + extra:
                detail = f'（{sold_on} 當天已有 {decimal_text(available)}、之後進貨 {decimal_text(extra)}）' if later else ''
                raise Problem(f"可扣庫存只有 {decimal_text(available + extra)} {p['unit']}{detail}，"
                              '請先確認盤點、效期與可售狀態', status=409)
            later_ids = {b['id'] for b in later}
            left, allocations = qty, []
            for b in batches + later:
                take = min(left, b['available'])
                if take <= 0:
                    continue
                allocation = {'batch_id': b['id'], 'version': b['version'],
                    'expires_on': b['expires_on'], 'quantity': decimal_text(take),
                    'before': b['quantity'], 'after': decimal_text(Decimal(b['quantity']) - take)}
                if b['id'] in later_ids:
                    allocation['later'] = True
                allocations.append(allocation)
                left -= take
                if left == 0:
                    break
            lines.append({'product_id': pid, 'name': p['name'], 'code': p['code'], 'unit': p['unit'],
                'quantity': decimal_text(qty), 'available': decimal_text(available + extra),
                'remaining': decimal_text(available + extra - qty), 'allocations': allocations})
            warnings += sale_warnings(conn, p, sold_on, qty, available, allocations, backfill)
        except Problem as error:
            raise Problem(f"{p['name']}：{error.message}", status=error.status, fields={'product_id': pid}) from None
    # 帶入的 LINE 訂單也算進確認碼：換了訂單就要重新預覽。
    result = {'sold_on': sold_on, 'note': note.strip(), 'items': lines, 'warnings': warnings,
              'line_orders': check_for_sheet(conn, command.get('line_orders'))}
    result['revision'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def post_sheet(conn, command, actor, today):
    def apply():
        plan = plan_sheet(conn, command, today)
        if command.get('revision') != plan['revision']:
            raise Problem('庫存或內容已變動，請重新預覽再確認扣庫存', status=409)
        if plan['warnings'] and command.get('confirm_warnings') is not True:
            raise Problem('這張單有需要確認的提醒，請重新檢查並勾選確認後再送出', status=409, code='sale_warnings')
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
