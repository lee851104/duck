import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
from datetime import date
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from .common import Problem, now
from .db import connect_db


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
    conn = connect_db(app.config['DB_PATH'])
    try:
        path = create_backup(app.config['DB_PATH'], app.config['DATA_DIR']/'media', app.config['BACKUP_DIR'])
        conn.execute('INSERT INTO backup_runs(created_at,path) VALUES(?,?)', (now(), str(path)))
        return {'filename': path.name}
    except Exception:
        conn.execute('INSERT INTO backup_runs(created_at,error) VALUES(?,?)', (now(), '備份未完成，請確認儲存空間與資料夾權限'))
        raise
    finally:
        conn.close()


def start_backup_worker(app):
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
