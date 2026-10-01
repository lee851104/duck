import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import current_app


class Problem(Exception):
    def __init__(self, message, code='invalid', status=400, fields=None):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status
        self.fields = fields or {}


def now():
    return datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')


def today():
    fixed = current_app.config.get('TODAY')
    return date.fromisoformat(fixed) if fixed else datetime.now(ZoneInfo('Asia/Taipei')).date()


def number(value, field='數量', optional=False, positive=False):
    if value is None or value == '':
        if optional:
            return None
        raise Problem(f'請填寫{field}')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise Problem(f'{field}必須是數字') from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise Problem(f'{field}必須是有效的' + ('正數' if positive else '非負數'))
    if result > Decimal('999999999') or result.as_tuple().exponent < -6:
        raise Problem(f'{field}過大或小數超過六位')
    return result


def decimal_text(value):
    if value is None:
        return None
    return format(Decimal(value).normalize(), 'f')


def valid_date(value, optional=True):
    if not value and optional:
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        raise Problem('日期格式應為 YYYY-MM-DD') from None


def required_text(value, label, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise Problem(f'請填寫有效的{label}（最多 {limit} 字）')
    return value.strip()


def paginate(items, page=1, page_size=10, maximum=10):
    try:
        page, page_size = int(page), min(int(page_size), maximum)
    except (TypeError, ValueError):
        raise Problem('分頁參數無效') from None
    if page < 1 or page_size < 1:
        raise Problem('分頁參數必須大於零')
    total = len(items)
    page = min(page, max(1, (total + page_size - 1) // page_size))
    return {'items': items[(page-1)*page_size:page*page_size], 'total': total,
            'page': page, 'page_size': page_size}


@contextmanager
def transaction(conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def mutate(conn, request_id, payload, callback):
    request_id = required_text(request_id, '請求識別碼', 100)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    with transaction(conn):
        previous = conn.execute('SELECT * FROM requests WHERE request_id=?', (request_id,)).fetchone()
        if previous:
            if previous['payload_hash'] != digest:
                raise Problem('這個操作識別碼已用於不同內容，請重新操作', status=409)
            return json.loads(previous['result'])
        result = callback()
        conn.execute('INSERT INTO requests VALUES(?,?,?)',
                     (request_id, digest, json.dumps(result, ensure_ascii=False)))
        return result


def record(conn, product_id, batch_id, kind, reason, before, after, actor, reversal=None):
    cur = conn.execute('''INSERT INTO movements
        (product_id,batch_id,kind,reason,before_value,after_value,actor,created_at,reversal_of)
        VALUES(?,?,?,?,?,?,?,?,?)''',
        (product_id, batch_id, kind, reason, before, after, str(actor), now(), reversal))
    return cur.lastrowid
