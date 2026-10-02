import hashlib
import json
import io
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZipFile, ZIP_DEFLATED

from .common import Problem, now, transaction

HEADERS = ['商品分類', '商品編號', '商品名稱', '商品售價', '商品單位', '是否含稅', '商品類型']


def invoice_rows(conn):
    rows, issues, codes = [], [], set()
    for r in conn.execute('SELECT * FROM invoice_items ORDER BY id'):
        item = dict(r)
        if item['product_id']:
            p = conn.execute('SELECT * FROM products WHERE id=?', (item['product_id'],)).fetchone()
            if p['unit'] != item['unit']:
                issues.append(f"{item['name']}：發票單位與商品單位不同，請確認規格")
            # Invoice platform codes belong to a separate namespace from stock SKUs.
            item.update(name=p['name'], price=p['price'], unit=p['unit'])
        elif not item['fixed']:
            issues.append(f"{item['name']}：尚未確認商品對應")
        if item['price'] is None:
            issues.append(f"{item['name']}：尚未設定售價")
        if not item['category'] or not item['code'] or item['tax'] not in {0, 1} or item['kind'] != 0:
            issues.append(f"{item['name']}：分類、品號或發票設定不完整")
        if item['code'] in codes:
            issues.append(f"重複發票商品編號：{item['code']}")
        codes.add(item['code'])
        rows.append([item['category'],item['code'],item['name'],item['price'],item['unit'],item['tax'],item['kind']])
    return rows, issues


def revision(conn):
    rows, issues = invoice_rows(conn)
    return hashlib.sha256(json.dumps([rows, issues], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def export_state(conn):
    marker = conn.execute("SELECT value FROM metadata WHERE key='latest_invoice_export'").fetchone()
    last = conn.execute('SELECT * FROM invoice_exports WHERE id=?', (marker[0],)).fetchone() if marker else None
    if last is None:
        tie = 'id' if getattr(conn, 'dialect', None) == 'postgres' else 'rowid'
        last = conn.execute(f'SELECT * FROM invoice_exports ORDER BY created_at DESC,{tie} DESC LIMIT 1').fetchone()
    rows, issues = invoice_rows(conn)
    return {'pending': not last or last['revision'] != revision(conn),
            'last_export': dict(last) if last else None, 'issues': issues, 'row_count': len(rows)}


def write_xlsx(path, rows):
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet = Element('worksheet', xmlns=ns)
    data = SubElement(sheet, 'sheetData')
    for r, values in enumerate([HEADERS]+rows, 1):
        row = SubElement(data, 'row', r=str(r))
        for col, value in enumerate(values):
            attrs = {'r': f'{chr(65+col)}{r}'}
            numeric = r > 1 and col in {3, 5, 6} and value is not None
            c = SubElement(row, 'c', {**attrs, 't': 'n' if numeric else 'inlineStr'})
            if numeric:
                SubElement(c, 'v').text = str(value)
            else:
                SubElement(SubElement(c, 'is'), 't').text = '' if value is None else str(value)
    with ZipFile(path, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="易發票系統" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', tostring(sheet, encoding='utf-8', xml_declaration=True))


def build_invoice_xlsx(conn, destination, storage=None):
    destination = Path(destination)
    if storage is None or not storage.remote:
        destination.mkdir(parents=True, exist_ok=True)
    with transaction(conn):
        rows, issues = invoice_rows(conn)
        if not rows:
            raise Problem('目前沒有發票商品，請先匯入及確認對應')
        if issues:
            raise Problem('請先處理發票商品的待確認資料', fields={'issues': issues})
        eid = uuid4().hex
        filename = f'易發票商品_{eid}.xlsx'
        if storage is not None and storage.remote:
            output = io.BytesIO()
            write_xlsx(output, rows)
            storage.put('exports/'+filename, output.getvalue())
        else:
            write_xlsx(destination/filename, rows)
        rev = revision(conn)
        conn.execute('INSERT INTO invoice_exports VALUES(?,?,?,?)', (eid, rev, filename, now()))
        conn.execute("INSERT INTO metadata(key,value) VALUES('latest_invoice_export',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (eid,))
    return {'export_id': eid, 'product_revision': rev, 'row_count': len(rows), 'issues': [], 'filename': filename}
