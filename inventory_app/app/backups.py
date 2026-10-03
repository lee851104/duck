import hashlib
import io
import os
import re
import subprocess
import json
import shutil
import sqlite3
import tempfile
import threading
from datetime import date
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

import requests

from .common import Problem, now, transaction
from .db import connect_db
from .storage import checked_key, storage_from_config


def create_backup(db_path, media_dir, backup_dir):
    db_path, media_dir, backup_dir = map(Path, (db_path, media_dir, backup_dir))
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir/f'inventory_{now()[:10]}_{uuid4().hex[:8]}.zip'
    partial = target.with_suffix('.partial')
    try:
        with tempfile.TemporaryDirectory(dir=backup_dir) as tmp:
            snapshot = Path(tmp)/'inventory.sqlite3'
            source = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True)
            destination = sqlite3.connect(snapshot)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            files = [('inventory.sqlite3', snapshot)]
            if media_dir.exists():
                files += [('media/'+p.name, p) for p in media_dir.iterdir() if p.is_file()]
            exports_dir = db_path.parent/'exports'
            if exports_dir.exists():
                files += [('exports/'+p.name, p) for p in exports_dir.iterdir() if p.is_file()]
            manifest = {}
            with ZipFile(partial, 'w', ZIP_DEFLATED) as z:
                for name, path in files:
                    content = path.read_bytes()
                    manifest[name] = hashlib.sha256(content).hexdigest()
                    z.writestr(name, content)
                z.writestr('manifest.json', json.dumps(manifest))
            with ZipFile(partial) as z:
                if z.testzip():
                    raise Problem('備份驗證失敗')
        partial.replace(target)
        return target
    finally:
        if partial.exists():
            partial.unlink()


def restore_backup(archive, destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise Problem('還原目錄必須為空，避免覆寫現有資料')
    with ZipFile(archive) as z:
        for info in z.infolist():
            path = (destination/info.filename).resolve()
            if not path.is_relative_to(destination) or '\\' in info.filename or ':' in info.filename:
                raise Problem('備份包含不安全的路徑')
        if 'manifest.json' not in z.namelist():
            raise Problem('備份缺少驗證清單')
        manifest = json.loads(z.read('manifest.json'))
        if 'inventory.sqlite3' not in manifest:
            raise Problem('備份缺少資料庫')
        for name, expected in manifest.items():
            if name not in z.namelist() or hashlib.sha256(z.read(name)).hexdigest() != expected:
                raise Problem('備份檔案驗證失敗')
        destination.mkdir(parents=True, exist_ok=True)
        for name in manifest:
            target = destination/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))


def backup_due(current_date, last_success):
    return not last_success or last_success[:10] != str(current_date)[:10]


def perform_backup(app):
    cloud = bool(app.config.get('CLOUD_MODE'))
    conn = connect_db(app.config['DATABASE_URL'], schema=app.config.get('DATABASE_SCHEMA', 'duck')) if cloud else connect_db(app.config['DB_PATH'])
    pending_id = None
    recorded = False
    try:
        if cloud:
            pending_id = _pending_backup(conn).get('id')
            result = create_cloud_backup(app.config)
            conn.execute('INSERT INTO backup_runs(created_at,path) VALUES(?,?)', (now(), result['path']))
            recorded = True
            return {'filename': result['filename']}
        path = create_backup(app.config['DB_PATH'], app.config['DATA_DIR']/'media', app.config['BACKUP_DIR'])
        conn.execute('INSERT INTO backup_runs(created_at,path) VALUES(?,?)', (now(), str(path)))
        return {'filename': path.name}
    except Exception:
        conn.execute('INSERT INTO backup_runs(created_at,error) VALUES(?,?)', (now(), '備份未完成，請確認儲存空間與資料夾權限'))
        recorded = True
        raise
    finally:
        try:
            if cloud and recorded:
                _clear_pending_backup(conn, pending_id)
        finally:
            conn.close()


def start_backup_worker(app):
    if app.config.get('CLOUD_MODE'):
        raise ValueError('Cloud backups require an explicit job or authenticated backup request')
    stop = threading.Event()
    def worker():
        while not stop.is_set():
            try:
                conn = connect_db(app.config['DB_PATH'])
                last = conn.execute('SELECT MAX(created_at) FROM backup_runs WHERE error IS NULL').fetchone()[0]
                conn.close()
                if backup_due(now()[:10], last):
                    perform_backup(app)
            except Exception:
                app.logger.exception('Scheduled backup failed')
            stop.wait(900)
    threading.Thread(target=worker, daemon=True, name='daily-backup').start()
    return stop


def dump_postgres(config, destination):
    """pg_dump provides one MVCC-consistent snapshot; no credentials in argv/logs."""
    from psycopg.conninfo import conninfo_to_dict
    schema = config.get('DATABASE_SCHEMA', 'duck')
    if not re.fullmatch(r'duck(?:_[a-z0-9_]+)?', schema):
        raise ValueError('Invalid backup schema')
    dsn = config.get('BACKUP_DATABASE_URL') or os.environ.get('BACKUP_DATABASE_URL') or config.get('DATABASE_URL')
    if not dsn:
        raise Problem('請設定備份資料庫連線', status=503)
    try:
        parameters = conninfo_to_dict(dsn)
    except Exception:
        raise Problem('備份資料庫連線設定不正確', status=503) from None
    if any('\n' in str(v) or '\r' in str(v) for v in parameters.values()):
        raise Problem('備份資料庫連線設定不正確', status=503)
    with tempfile.TemporaryDirectory() as tmp:
        service = Path(tmp)/'pg_service.conf'
        service.write_text('[duck_backup]\n'+''.join(f'{key}={value}\n' for key,value in parameters.items()), encoding='utf-8')
        service.chmod(0o600)
        env = {key:value for key,value in os.environ.items() if not key.startswith('PG')}
        env.update(PGSERVICEFILE=str(service), PGSERVICE='duck_backup')
        try:
            # The runtime role reads every application row through its RLS policy,
            # without BYPASSRLS. INSERT data also supports restoring with RLS on.
            subprocess.run([config.get('PG_DUMP_BIN', 'pg_dump'), '--format=custom', '--no-owner', '--no-acl',
                '--enable-row-security', '--inserts',
                '--schema='+schema, '--file='+str(destination)], env=env, check=True, capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError):
            raise Problem('資料庫備份失敗；請確認相容版本 pg_dump、備份帳號權限及連線設定', code='backup', status=503) from None
    if not Path(destination).is_file() or not Path(destination).read_bytes().startswith(b'PGDMP'):
        raise Problem('資料庫備份格式驗證失敗', code='backup', status=503)


def validate_cloud_backup(content):
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            if set(archive.namelist()) != {'database.dump', 'manifest.json'} or archive.testzip():
                raise ValueError()
            manifest = json.loads(archive.read('manifest.json'))
            database = archive.read('database.dump')
            if (manifest['format'] != 'duck-postgres-backup-v1'
                    or not re.fullmatch(r'duck(?:_[a-z0-9_]+)?', manifest['schema'])
                    or not database.startswith(b'PGDMP')
                    or hashlib.sha256(database).hexdigest() != manifest['database']['sha256']):
                raise ValueError()
            for key, entry in manifest['objects'].items():
                checked_key(key)
                if not key.startswith(('media/', 'exports/')) or not re.fullmatch('[a-f0-9]{64}', entry['sha256']) or not isinstance(entry['size'], int) or entry['size'] < 0:
                    raise ValueError()
            return manifest
    except (BadZipFile, ValueError, KeyError, TypeError, AttributeError):
        raise Problem('雲端備份驗證失敗', code='backup', status=503) from None


def create_cloud_backup(config):
    storage = storage_from_config(config)
    if not storage.remote:
        raise ValueError('Cloud backup requires remote storage')
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp)/'database.dump'
        dump_postgres(config, dump)
        # Objects are immutable and uploaded before DB commits; listing after the
        # snapshot safely includes every object referenced by the snapshot.
        objects = {}
        for prefix in ('media', 'exports'):
            for key in storage.list(prefix):
                data = storage.read(key)
                objects[key] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
        database = dump.read_bytes()
        manifest = {'format': 'duck-postgres-backup-v1', 'schema': config.get('DATABASE_SCHEMA', 'duck'),
            'created_at': now(), 'database': {'sha256': hashlib.sha256(database).hexdigest(), 'size': len(database)},
            'objects': objects}
        output = io.BytesIO()
        with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('database.dump', database)
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True))
        content = output.getvalue()
        validate_cloud_backup(content)
        key = 'backups/'+manifest['created_at'][:19].replace(':', '').replace('T', '_')+'_'+hashlib.sha256(content).hexdigest()+'.zip'
        storage.put(key, content)
        # Retain newest successful snapshot for each of seven days. Never delete
        # media/exports: earlier DB snapshots may still reference them.
        keys = sorted(k for k in storage.list('backups') if re.fullmatch(r'backups/\d{4}-\d{2}-\d{2}_(?:\d{6}_)?[a-f0-9]{64}\.zip', k))
        keep = set()
        days = set()
        for old in reversed(keys):
            day = old[8:18]
            if day not in days and len(days) < 7:
                keep.add(old)
                days.add(day)
        storage.delete_backups([old for old in keys if old not in keep])
        return {'filename': key.rsplit('/', 1)[1], 'path': key}


_BACKUP_PENDING_KEY = 'cloud_backup_pending'
_JOB_PATTERN = r'projects/[a-z0-9][a-z0-9-]*/locations/[a-z]+-[a-z]+[0-9]+/jobs/[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?'
_OPERATION_PATTERN = r'projects/[a-z0-9][a-z0-9-]*/locations/[a-z]+-[a-z]+[0-9]+/operations/[A-Za-z0-9_-]+'


def _queue_unavailable():
    return Problem('雲端備份啟動未確認；請管理員核對備份工作狀態與執行權限', code='backup', status=503)


def _pending_backup(conn):
    row = conn.execute('SELECT value FROM metadata WHERE key=?', (_BACKUP_PENDING_KEY,)).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row[0])
        if not isinstance(value, dict) or not value.get('id'):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise _queue_unavailable() from None


def _clear_pending_backup(conn, pending_id):
    if not pending_id:
        return
    with transaction(conn):
        if _pending_backup(conn).get('id') == pending_id:
            conn.execute('DELETE FROM metadata WHERE key=?', (_BACKUP_PENDING_KEY,))


def enqueue_cloud_backup(app, conn):
    """Reserve one durable intent before launching a bounded async job request.

    No automatic retry after an unknown POST outcome: Cloud Run jobs.run has no
    request ID deduplication field. The worker clears its matching intent after
    recording success/failure; cancellation before worker startup needs operator
    reconciliation. Only run.jobs.run is needed, not operation polling access.
    """
    resource = app.config.get('BACKUP_JOB_RESOURCE', '')
    if not isinstance(resource, str) or not re.fullmatch(_JOB_PATTERN, resource):
        raise Problem('尚未設定有效的雲端備份工作，請聯絡管理員', code='backup', status=503)
    pending = {'id': uuid4().hex, 'submitted_at': now(), 'job': resource}
    with transaction(conn):
        if _pending_backup(conn):
            raise Problem('備份已排入或正在執行；若長時間未完成，請管理員核對工作狀態', code='backup_pending', status=409)
        conn.execute('INSERT INTO metadata(key,value) VALUES(?,?)', (_BACKUP_PENDING_KEY, json.dumps(pending)))
    # A token failure is known to precede POST, so safely release that intent.
    try:
        response = requests.request('GET',
            'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
            headers={'Metadata-Flavor': 'Google'}, timeout=(2, 5), allow_redirects=False)
        if response.status_code != 200:
            raise ValueError()
        token = response.json().get('access_token')
        if not isinstance(token, str) or not token or any(ord(char) <= 32 or ord(char) == 127 for char in token):
            raise ValueError()
    except (requests.RequestException, ValueError, AttributeError):
        _clear_pending_backup(conn, pending['id'])
        raise _queue_unavailable() from None
    try:
        response = requests.request('POST', 'https://run.googleapis.com/v2/'+resource+':run',
            headers={'Authorization': 'Bearer '+token}, json={}, timeout=(3, 10), allow_redirects=False)
    except requests.RequestException:
        # Keep the committed intent: the remote service may have accepted it.
        raise _queue_unavailable() from None
    if response.status_code in (400, 401, 403, 404, 429):
        _clear_pending_backup(conn, pending['id'])
        raise _queue_unavailable()
    try:
        if response.status_code not in (200, 201, 202):
            raise ValueError()
        operation = response.json().get('name')
        if not isinstance(operation, str) or not re.fullmatch(_OPERATION_PATTERN, operation):
            raise ValueError()
    except (ValueError, AttributeError):
        raise _queue_unavailable() from None
    with transaction(conn):
        if _pending_backup(conn).get('id') == pending['id']:
            pending['operation'] = operation
            conn.execute('UPDATE metadata SET value=? WHERE key=?', (json.dumps(pending), _BACKUP_PENDING_KEY))
    return {'queued': True}
