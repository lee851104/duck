"""Publish three consistent local Excel snapshots without modifying raw sources."""
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
from datetime import date
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .common import Problem, now
from .db import connect_db
from .exports import invoice_rows, write_inventory_xlsx, write_xlsx
from .media import REL, relations

FILENAMES = {'inventory': '庫存管理.xlsx', 'catalog': '商品價目表.xlsx', 'invoice': '發票系統.xlsx'}


def replace_price(xml, address, value):
    # Patch only the cell. Reserializing the entire sheet can break Excel's
    # namespace extension attributes and its embedded drawing references.
    pattern = rb'<c\b[^>]*\br="' + address.encode('ascii') + rb'"[^>]*(?:/>|>.*?</c>)'
    matches = list(re.finditer(pattern, xml, re.S))
    if len(matches) != 1:
        raise ValueError('找不到唯一的價目表售價儲存格：' + address)
    old = matches[0]
    start = old.group().split(b'>', 1)[0].rstrip(b'/')
    start = re.sub(rb'\s+t="[^"]*"', b'', start)
    value_xml = b'' if value is None else b'<v>' + str(value).encode('ascii') + b'</v>'
    return xml[:old.start()] + start + b'>' + value_xml + b'</c>' + xml[old.end():]


def write_catalog(conn, source, destination):
    changes = {}
    for r in conn.execute('''SELECT c.source,c.name,c.brand,c.specification,p.price FROM catalog_cards c
            JOIN products p ON p.id=c.product_id WHERE c.pricing_mode='product' '''):
        sheet, address = r['source'].rsplit('!', 1)
        if not re.fullmatch(r'[A-Z]+[1-9][0-9]*', address):
            raise ValueError('價目表來源位置無效')
        changes.setdefault(sheet, {})[address] = dict(r)
    with ZipFile(source) as src, ZipFile(destination, 'w') as dst:
        rels = relations(src, 'xl/workbook.xml')
        sheets = {s.get('name'): rels[s.attrib[REL]] for s in
                  ET.fromstring(src.read('xl/workbook.xml')).findall('.//{*}sheet')}
        if not set(changes) <= set(sheets):
            raise ValueError('價目表工作表已變動，請重新核對來源')
        shared = []
        if 'xl/sharedStrings.xml' in src.namelist():
            shared = [''.join(t.text or '' for t in item.findall('.//{*}t'))
                      for item in ET.fromstring(src.read('xl/sharedStrings.xml'))]
        by_path = {sheets[name]: cells for name, cells in changes.items()}
        for entry in src.infolist():
            if entry.filename in by_path:
                content = src.read(entry)
                cells = {c.get('r'): c for c in ET.fromstring(content).findall('.//{*}c')}
                for address, item in by_path[entry.filename].items():
                    column, row = re.fullmatch(r'([A-Z]+)([0-9]+)', address).groups()
                    for field, offset in [('brand', 3), ('name', 2), ('specification', 1)]:
                        cell = cells.get(column+str(int(row)-offset))
                        value = ''
                        if cell is not None:
                            if cell.get('t') == 'inlineStr':
                                value = ''.join(t.text or '' for t in cell.findall('.//{*}t'))
                            else:
                                value = cell.findtext('{*}v') or ''
                                if cell.get('t') == 's':
                                    value = shared[int(value)]
                        if value != str(item[field] or ''):
                            raise ValueError('價目表來源品項已變更：' + item['source'])
                    content = replace_price(content, address, item['price'])
                dst.writestr(entry, content)
            else:
                # Streaming preserves every image, formatting part and relationship.
                with src.open(entry) as incoming, dst.open(entry, 'w') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    return sum(map(len, changes.values()))


def snapshot_revision(conn, day):
    payload = [day.isoformat()]
    for table in ('products', 'batches', 'catalog_cards', 'invoice_items'):
        payload.append([dict(r) for r in conn.execute(f'SELECT * FROM {table} ORDER BY id')])
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ExcelSync:
    def __init__(self, app):
        self.app = app
        self.root = (Path(app.config['DATA_DIR'])/'excel_sync').resolve()
        self.manifest = self.root/'latest.json'
        self.event = threading.Event()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.build_lock = threading.Lock()
        self.pending = False
        self.running = False
        self.error = None
        self.last = None
        self.thread = None
        if self.manifest.is_file():
            self.last = json.loads(self.manifest.read_text('utf-8'))

    def status(self):
        with self.lock:
            return {'pending': self.pending, 'running': self.running, 'error': self.error,
                    'last': self.last, 'root': str(self.root)}

    def request(self):
        with self.lock:
            self.pending = True
        self.event.set()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._worker, name='excel-sync', daemon=True)
            self.thread.start()
            self.request()
        return self.stop

    def _worker(self):
        while not self.stop.is_set():
            if not self.event.wait(1):
                continue
            # Coalesce quick edits without blocking the sale/count request.
            if self.stop.wait(.3):
                return
            try:
                self.sync_once()
            except Exception:
                logging.getLogger(__name__).exception('Local Excel synchronization failed')

    def snapshot(self):
        snapshot = connect_db(':memory:')
        source_db = sqlite3.connect(f"file:{Path(self.app.config['DB_PATH']).as_posix()}?mode=ro", uri=True)
        try:
            source_db.backup(snapshot)
        finally:
            source_db.close()
        return snapshot

    def template(self):
        templates = list(Path(self.app.config['SOURCE_DIR']).glob('*價目表*.xlsx'))
        if len(templates) != 1:
            raise ValueError('原始資料夾需保留一份商品價目表 Excel')
        return templates[0]

    def sync_once(self):
        with self.build_lock:
            with self.lock:
                self.event.clear()
                self.pending = False
                self.running = True
                self.error = None
            snapshot = None
            folder = None
            try:
                snapshot = self.snapshot()
                day = date.fromisoformat(self.app.config.get('TODAY') or now()[:10])
                revision = snapshot_revision(snapshot, day)
                template = self.template()
                with template.open('rb') as source:
                    source_hash = hashlib.file_digest(source, 'sha256').hexdigest()
                if (self.last and self.last['revision'] == revision and self.last['source_sha256'] == source_hash
                        and all((Path(self.last['folder'])/name).is_file() for name in FILENAMES.values())):
                    return self.last
                rows, issues = invoice_rows(snapshot)
                if issues:
                    raise ValueError('發票資料需先確認：' + '；'.join(issues[:3]))
                self.root.mkdir(parents=True, exist_ok=True)
                folder = self.root/(now()[:19].replace(':', '').replace('T', '_')+'_'+uuid4().hex[:8])
                folder.mkdir()
                count = write_inventory_xlsx(snapshot, folder/FILENAMES['inventory'], day)
                linked = write_catalog(snapshot, template, folder/FILENAMES['catalog'])
                write_xlsx(folder/FILENAMES['invoice'], rows)
                result = {'created_at': now(), 'revision': revision, 'source_sha256': source_hash,
                          'folder': str(folder), 'files': FILENAMES, 'batch_count': count,
                          'catalog_linked': linked, 'invoice_count': len(rows)}
                (folder/'snapshot.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
                temporary = self.manifest.with_suffix('.tmp')
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
                os.replace(temporary, self.manifest)
                with self.lock:
                    self.last = result
                folder = None  # A published generation must never be removed on failure.
                self._prune()
                return result
            except Exception as exc:
                with self.lock:
                    self.error = 'Excel 同步未完成：' + str(exc) + '。系統中的庫存已保存，可按重新同步。'
                if folder:
                    self._remove(folder)
                raise
            finally:
                if snapshot is not None:
                    snapshot.close()
                with self.lock:
                    self.running = False

    def _remove(self, folder):
        resolved = folder.resolve()
        if resolved.parent != self.root or not re.fullmatch(r'\d{4}-\d{2}-\d{2}_\d{6}_[0-9a-f]{8}', resolved.name):
            raise ValueError('同步資料夾路徑無效')
        try:
            shutil.rmtree(resolved)
        except OSError:
            pass  # Excel may still have an older snapshot open.

    def _prune(self):
        completed = sorted((p for p in self.root.iterdir() if p.is_dir() and (p/'snapshot.json').is_file()),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        for folder in completed[2:]:
            if str(folder) != self.last['folder']:
                self._remove(folder)

    def download(self):
        state = self.status()
        if state['pending'] or state['running']:
            raise Problem('Excel 正在同步，完成後即可下載', status=409)
        if state['error'] or not state['last']:
            raise Problem('Excel 尚未同步完成，請重新同步', status=409)
        path = Path(state['last']['folder'])/FILENAMES['inventory']
        if not path.is_file():
            raise Problem('匯出檔不存在，請重新同步', status=409)
        return path
