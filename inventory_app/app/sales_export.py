"""Read-only exports of draft quantities or the original posted sales snapshot."""
import io
from datetime import date

from .common import Problem, decimal_text
from .daily_sales import sale_date, sheet_detail
from .exports import write_xlsx
from .inventory import quantity_for


def draft_sheet(conn, command, today):
    if not isinstance(command, dict):
        raise Problem('銷售單格式不正確')
    day = sale_date(command.get('sold_on'), today)
    note = command.get('note', '')
    if not isinstance(note, str) or len(note) > 500:
        raise Problem('備註最多 500 字')
    items = command.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise Problem('請加入 1 至 200 項商品')
    seen, lines = set(), []
    for item in items:
        if not isinstance(item, dict) or type(item.get('product_id')) is not int:
            raise Problem('商品格式不正確')
        pid = item['product_id']
        if pid in seen:
            raise Problem('同一商品請合併數量，只填一列')
        seen.add(pid)
        row = conn.execute('SELECT id,code,name,unit FROM products WHERE id=?', (pid,)).fetchone()
        if not row:
            raise Problem('找不到部分商品，請重新選取', status=404)
        p = dict(row)
        lines.append({**p, 'quantity': decimal_text(quantity_for(p, item.get('quantity'), True))})
    return {'sold_on': day, 'note': note.strip(), 'status': 'draft', 'items': lines}


def export_sales(conn, today, command=None, sid=None):
    sheet = sheet_detail(conn, sid) if sid is not None else draft_sheet(conn, command, today)
    status = {'draft': '草稿／未扣庫存', 'posted': '已扣庫存', 'void': '已沖銷'}[sheet['status']]
    day = date.fromisoformat(sheet['sold_on'])
    serial = (day - date(1899, 12, 30)).days
    note = sheet['note']
    if sheet['status'] == 'void':
        note += ('\n' if note else '') + '沖銷原因：' + sheet['void_reason']
    rows = [[serial, p['code'], p['name'], p['quantity'], p['unit'], status,
             str(sheet['id']) if sid is not None else '', note] for p in sheet['items']]
    output = io.BytesIO()
    write_xlsx(output, rows, headers=['銷售日期', '品號', '商品', '數量', '單位', '狀態', '銷售單號', '備註'],
               sheet_name='銷售明細', numeric_columns={0, 3})
    output.seek(0)
    suffix = '草稿' if sid is None else f"{sid}_{status}"
    return output, f"每日銷售_{sheet['sold_on']}_{suffix}.xlsx"
