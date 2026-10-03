"""Request-scoped Excel generation from one consistent PostgreSQL snapshot.

Cloud disk is only a disposable cache. The source workbook is stored as verified
immutable chunks in private storage; all three outputs can be regenerated.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED
from urllib.parse import quote
from flask import Response

from .common import Problem
from .db import connect_db, get_db, init_db
from .excel_sync import ExcelSync, FILENAMES
from .storage import get_storage


def stream_download(path, filename):
    # Cloud Run caps non-streamed HTTP/1 responses at 32 MiB. A generator (not
    # wsgi.file_wrapper) lets Waitress use chunked transfer for the photo workbook.
    source = Path(path).open('rb')
    def chunks():
        try:
            while data := source.read(64 * 1024):
                yield data
        finally:
            source.close()
    response = Response(chunks(), mimetype='application/zip')
    response.headers['Content-Disposition'] = "attachment; filename=excel-backup.zip; filename*=UTF-8''"+quote(filename)
    response.headers['Cache-Control'] = 'private, no-store'
    response.call_on_close(source.close)
    return response


class CloudExcelSync(ExcelSync):
    def _prune(self):
        for folder in self.root.iterdir():
            if folder.is_dir() and (folder/'snapshot.json').is_file() and str(folder) != self.last['folder']:
                self._remove(folder)

    def start(self):
        raise RuntimeError('Cloud Excel generation must run inside a request')

    def status(self):
        state = super().status()
        state.update(cloud=True, stale=state['pending'], pending=False, root=None)
        if state['last']:
            state['last'] = {k:v for k,v in state['last'].items() if k != 'folder'}
        return state

    def snapshot(self):
        source = get_db()
        snapshot = connect_db(':memory:')
        init_db(snapshot)
        try:
            with source.raw.transaction():
                source.raw.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                for table in ('products', 'batches', 'catalog_cards', 'invoice_items'):
                    for row in source.execute('SELECT * FROM '+table+' ORDER BY id'):
                        item = dict(row)
                        columns = ','.join('"'+key+'"' for key in item)
                        snapshot.execute(f'INSERT INTO {table} ({columns}) VALUES({",".join("?" for _ in item)})', tuple(item.values()))
            return snapshot
        except Exception:
            snapshot.close()
            raise

    def template(self):
        marker = get_db().execute("SELECT value FROM metadata WHERE key='excel_template'").fetchone()
        if not marker:
            raise Problem('價目表原始範本尚未上傳，請聯絡管理員', status=409)
        manifest = json.loads(marker[0])
        digest = manifest.get('sha256', '')
        chunks = manifest.get('chunks', [])
        if not re.fullmatch('[a-f0-9]{64}', digest) or not chunks or len(chunks) > 100:
            raise Problem('價目表範本清單無效', status=503)
        folder = Path(self.app.config['DATA_DIR'])/'templates'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder/(digest+'.xlsx')
        if path.is_file():
            return path
        temporary = path.with_suffix('.tmp')
        hasher = hashlib.sha256()
        try:
            with temporary.open('wb') as output:
                for key in chunks:
                    if not re.fullmatch(r'templates/[a-f0-9]{64}/[0-9]{3}\.part', key):
                        raise Problem('價目表範本路徑無效', status=503)
                    content = get_storage().read(key)
                    hasher.update(content)
                    output.write(content)
            if hasher.hexdigest() != digest:
                raise Problem('價目表範本驗證失敗', status=503)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def download(self):
        result = self.sync_once()
        return Path(result['folder'])/FILENAMES['inventory']

    def bundle(self):
        # Serialize packaging with generation/pruning. sync_once already captures
        # one database revision, so every workbook in the ZIP agrees.
        self.sync_once()
        with self.build_lock:
            folder = Path(self.last['folder'])
            path = folder/'每日Excel備援.zip'
            if not path.is_file():
                temporary = path.with_suffix('.tmp')
                with ZipFile(temporary, 'w', ZIP_STORED) as archive:
                    for name in FILENAMES.values():
                        archive.write(folder/name, name)
                    archive.write(folder/'snapshot.json', 'snapshot.json')
                os.replace(temporary, path)
            return path
