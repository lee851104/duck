"""Upload a local media snapshot to private storage without renaming references.

Run from inventory_app: python tools/migrate_media.py --media-dir <snapshot/media>
    --manifest <private-output/media-manifest.json>
Credentials are read only from SUPABASE_* environment variables.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.common import Problem
from app.storage import storage_from_config


def migrate_media(media_dir, storage, manifest_path, exports_dir=None):
    media_dir, manifest_path = Path(media_dir), Path(manifest_path)
    if not storage.remote or not media_dir.is_dir():
        raise ValueError('A local snapshot media directory and remote storage are required')
    files = sorted(path for path in media_dir.iterdir() if path.is_file())
    if any(path.is_symlink() or not re.fullmatch(r'[a-f0-9]{64}(\.thumb)?\.(jpg|jpeg|png|webp|gif)', path.name) for path in files):
        raise Problem('媒體快照包含不支援的檔名或連結，請先核對來源')
    objects = [('media/'+path.name, path) for path in files]
    if exports_dir is not None:
        exports_dir = Path(exports_dir)
        if not exports_dir.is_dir():
            raise ValueError('Export snapshot directory does not exist')
        for path in sorted(exports_dir.iterdir()):
            if not path.is_file() or path.is_symlink() or not re.fullmatch(r'易發票商品_[a-f0-9]+\.xlsx', path.name):
                raise Problem('發票快照包含不支援的檔名或連結')
            objects.append(('exports/'+path.name, path))
    manifest = {'format': 'duck-media-v1', 'objects': {}}
    for key, path in objects:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        # Verify remote bytes on every resume; an old manifest is not proof that
        # an object still exists and has the expected content.
        if storage.exists(key):
            if hashlib.sha256(storage.read(key)).hexdigest() != digest:
                raise Problem('雲端媒體與來源快照不同；停止遷移，原檔未覆寫', code='storage', status=409)
        else:
            storage.put(key, content)
        manifest['objects'][key] = {'sha256': digest, 'size': len(content)}
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest_path.with_suffix(manifest_path.suffix+'.partial')
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding='utf-8')
        temporary.replace(manifest_path)
    return {'count': len(objects), 'bytes': sum(entry['size'] for entry in manifest['objects'].values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media-dir', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--exports-dir', type=Path)
    args = parser.parse_args()
    config = {key: os.environ.get(key, '') for key in ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY')}
    config.update(STORAGE_BACKEND='supabase', SUPABASE_BUCKET=os.environ.get('SUPABASE_BUCKET', 'duck-private'))
    try:
        result = migrate_media(args.media_dir, storage_from_config(config), args.manifest, args.exports_dir)
    except (Problem, ValueError, OSError):
        parser.exit(1, 'Media migration failed; check private configuration, snapshot and remote integrity. No secrets logged.\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
