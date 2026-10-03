"""Explicit cloud backup job or verified offline restore bundle download.

python tools/cloud_backup.py backup
python tools/cloud_backup.py download --key backups/<key>.zip --output <new-directory>
Restore database.dump using compatible pg_restore into an EMPTY isolated database,
then apply runtime grants with the database migration tool. Never overwrite live DB.
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.backups import perform_backup, validate_cloud_backup
from app.common import Problem
from app.storage import storage_from_config


def download_bundle(storage, key, destination):
    if not re.fullmatch(r'backups/\d{4}-\d{2}-\d{2}_(?:\d{6}_)?[a-f0-9]{64}\.zip', key):
        raise Problem('備份物件名稱不正確')
    destination = Path(destination).resolve()
    if destination.exists():
        raise Problem('還原目的目錄必須尚未存在，避免覆寫現有資料')
    content = storage.read(key)
    if hashlib.sha256(content).hexdigest() != key.rsplit('_', 1)[1][:-4]:
        raise Problem('雲端備份內容雜湊不符')
    manifest = validate_cloud_backup(content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        bundle = Path(tmp)/'bundle'
        bundle.mkdir()
        with ZipFile(io.BytesIO(content)) as archive:
            (bundle/'database.dump').write_bytes(archive.read('database.dump'))
            (bundle/'manifest.json').write_bytes(archive.read('manifest.json'))
        for name, entry in manifest['objects'].items():
            data = storage.read(name)
            if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise Problem('雲端媒體完整性驗證失敗，未完成還原')
            path = bundle/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        bundle.rename(destination)
    return {'objects': len(manifest['objects'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['backup', 'download'])
    parser.add_argument('--key')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    config = {key: os.environ.get(key, '') for key in ('DATABASE_URL', 'BACKUP_DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_KEY')}
    config.update(CLOUD_MODE=True, STORAGE_BACKEND='supabase', DATABASE_SCHEMA=os.environ.get('DATABASE_SCHEMA', 'duck'),
        SUPABASE_BUCKET=os.environ.get('SUPABASE_BUCKET', 'duck-private'), PG_DUMP_BIN=os.environ.get('PG_DUMP_BIN', 'pg_dump'))
    try:
        if args.command == 'backup':
            result = perform_backup(SimpleNamespace(config=config))
        else:
            if not args.key or not args.output:
                parser.error('download requires --key and --output')
            result = download_bundle(storage_from_config(config), args.key, args.output)
    except Exception:
        parser.exit(1, 'Cloud backup operation failed. Check connection, pg_dump version, permissions and object integrity; secrets were not logged.\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
