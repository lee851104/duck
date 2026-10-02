import hashlib
import json
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
    last = conn.execute('SELECT * FROM invoice_exports ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()
    rows, issues = invoice_rows(conn)
    return {'pending': not last or last['revision'] != revision(conn),
            'last_export': dict(last) if last else None, 'issues': issues, 'row_count': len(rows)}


def write_xlsx(path, rows, headers=None, sheet_name='易發票系統', numeric_columns=None):
    headers = HEADERS if headers is None else headers
    numeric_columns = {3, 5, 6} if numeric_columns is None else numeric_columns
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet = Element('worksheet', xmlns=ns)
    if sheet_name == '庫存管理':
        views = SubElement(sheet, 'sheetViews')
        view = SubElement(views, 'sheetView', workbookViewId='0')
        SubElement(view, 'pane', ySplit='1', topLeftCell='A2', activePane='bottomLeft', state='frozen')
        cols = SubElement(sheet, 'cols')
        for i, width in enumerate([17, 19, 17, 38, 10, 14, 14, 16, 16, 14, 30, 14, 14, 12], 1):
            SubElement(cols, 'col', min=str(i), max=str(i), width=str(width), customWidth='1')
    data = SubElement(sheet, 'sheetData')
    for r, values in enumerate([headers]+rows, 1):
        row = SubElement(data, 'row', r=str(r))
        if sheet_name == '庫存管理':
            row.set('ht', '30' if r == 1 else '25')
            row.set('customHeight', '1')
        for col, value in enumerate(values):
            attrs = {'r': f'{chr(65+col)}{r}'}
            if sheet_name == '庫存管理' and r == 1:
                attrs['s'] = '1'
            if value is None:
                SubElement(row, 'c', attrs)
                continue
            numeric = r > 1 and col in numeric_columns and value is not None
            c = SubElement(row, 'c', {**attrs, 't': 'n' if numeric else 'inlineStr'})
            if numeric:
                SubElement(c, 'v').text = str(value)
            else:
                SubElement(SubElement(c, 'is'), 't').text = '' if value is None else str(value)
    if sheet_name == '庫存管理':
        SubElement(sheet, 'autoFilter', ref=f'A1:N{len(rows)+1}')
    with ZipFile(path, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml', f'''<styleSheet xmlns="{ns}">
            <fonts count="2"><font><sz val="11"/><name val="Microsoft JhengHei"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Microsoft JhengHei"/></font></fonts>
            <fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF365F3E"/><bgColor indexed="64"/></patternFill></fill></fills>
            <borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
            <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf></cellXfs>
            <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>''')
        z.writestr('xl/worksheets/sheet1.xml', tostring(sheet, encoding='utf-8', xml_declaration=True))


def inventory_rows(conn, day):
    from datetime import date
    rows = []
    for r in conn.execute('''SELECT p.*,b.id AS batch_id,b.quantity,b.cost,b.received_on,
            b.expires_on,b.saleable FROM products p JOIN batches b ON b.product_id=p.id
            ORDER BY p.category,p.code,b.expires_on IS NULL,b.expires_on,b.id'''):
        days = (date.fromisoformat(r['expires_on']) - day).days if r['expires_on'] else None
        status = []
        if r['quantity'] is None:
            status.append('未盤點')
        if days is not None and days < 0:
            status.append('已過期')
        elif not r['saleable']:
            status.append('未確認可售')
        elif days is None:
            status.append('效期未知／已確認可售')
        elif days <= 30:
            status.append('即期品')
        else:
            status.append('正常')
        rows.append([r['category'],r['supplier'],r['code'],r['name'],r['unit'],r['cost'],r['price'],
                     r['received_on'],r['expires_on'],days,'／'.join(status),r['quantity'],r['minimum'],r['batch_id']])
    return rows


def write_inventory_xlsx(conn, path, day):
    rows = inventory_rows(conn, day)
    write_xlsx(path, rows, ['類別','供應商','品號','品名','單位','進價','售價','進貨日期',
                          '有效期限','剩餘天數','管理','庫存','最低庫存','批次編號'],
               '庫存管理', {5,6,9,11,12,13})
    return len(rows)


def build_invoice_xlsx(conn, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with transaction(conn):
        rows, issues = invoice_rows(conn)
        if not rows:
            raise Problem('目前沒有發票商品，請先匯入及確認對應')
        if issues:
            raise Problem('請先處理發票商品的待確認資料', fields={'issues': issues})
        eid = uuid4().hex
        filename = f'易發票商品_{eid}.xlsx'
        write_xlsx(destination/filename, rows)
        rev = revision(conn)
        conn.execute('INSERT INTO invoice_exports VALUES(?,?,?,?)', (eid, rev, filename, now()))
    return {'export_id': eid, 'product_revision': rev, 'row_count': len(rows), 'issues': [], 'filename': filename}
