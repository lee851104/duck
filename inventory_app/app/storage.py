"""Private durable objects; all browser access remains through authorized Flask routes."""
import base64
import json
import io
import mimetypes
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

import requests
from flask import current_app, send_file

from .common import Problem


def checked_key(key):
    if not isinstance(key, str) or not key or '\\' in key or ':' in key:
        raise Problem('物件路徑不正確')
    path = PurePosixPath(key)
    if path.is_absolute() or '..' in path.parts or str(path) != key:
        raise Problem('物件路徑不正確')
    return key


def unavailable():
    return Problem('雲端儲存暫時無法使用，請稍後重試或請管理員檢查儲存設定', code='storage', status=503)


class LocalStorage:
    remote = False

    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, key):
        path = (self.root/checked_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise Problem('物件路徑不正確')
        return path

    def read(self, key):
        try:
            return self.path(key).read_bytes()
        except FileNotFoundError:
            raise Problem('找不到檔案', status=404) from None

    def exists(self, key):
        return self.path(key).is_file()

    def put(self, key, content):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != content:
                raise Problem('物件內容與原檔不一致', code='storage', status=409)
            return key
        # Exclusive creation keeps immutable references safe across retries.
        try:
            with path.open('xb') as output:
                output.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise Problem('物件內容與原檔不一致', code='storage', status=409) from None
        return key


def service_key_headers(key):
    """Classify key format locally; Supabase still verifies actual credentials."""
    message = 'SUPABASE_SERVICE_KEY must be a backend secret key or legacy service_role JWT'
    if not isinstance(key, str):
        raise ValueError(message)
    if re.fullmatch(r'sb_secret_[A-Za-z0-9_-]+', key):
        # New opaque secrets are not JWTs and must never be sent as Bearer tokens.
        return {'apikey': key}
    if not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', key):
        raise ValueError(message)
    try:
        payload = key.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload) % 4)))
        if not isinstance(claims, dict) or claims.get('role') != 'service_role':
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError(message) from None
    return {'apikey': key, 'Authorization': 'Bearer '+key}


class SupabaseStorage:
    remote = True

    def __init__(self, url, service_key, bucket='duck-private'):
        parsed = urlsplit(url or '')
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('SUPABASE_URL must be an HTTPS project origin')
        if not service_key or not re.fullmatch(r'[a-zA-Z0-9_-]+', bucket or ''):
            raise ValueError('Private Supabase storage configuration is incomplete')
        self.base = url.rstrip('/')+'/storage/v1/'
        self.bucket = bucket
        self.session = requests.Session()
        self.session.headers.update(service_key_headers(service_key))
        self._private_checked = False

    def _request(self, method, path, **kwargs):
        try:
            return self.session.request(method, self.base+path, timeout=(5, 45), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise unavailable() from None

    def ensure_private(self):
        if not self._private_checked:
            response = self._request('GET', 'bucket/'+self.bucket)
            try:
                valid = response.status_code == 200 and response.json().get('public') is False
            except (ValueError, AttributeError):
                valid = False
            if not valid:
                raise unavailable()
            self._private_checked = True

    def _object(self, key):
        self.ensure_private()
        return 'object/'+self.bucket+'/'+quote(checked_key(key), safe='/')

    def read(self, key):
        response = self._request('GET', self._object(key))
        if response.status_code == 404:
            raise Problem('找不到檔案', status=404)
        # Storage may wrap an object-not-found as HTTP 400.
        if response.status_code == 400:
            try:
                if str(response.json().get('statusCode')) == '404':
                    raise Problem('找不到檔案', status=404)
            except ValueError:
                pass
        if response.status_code != 200:
            raise unavailable()
        return response.content

    def exists(self, key):
        try:
            self.read(key)
            return True
        except Problem as error:
            if error.status == 404:
                return False
            raise

    def put(self, key, content):
        response = self._request('POST', self._object(key), data=content,
            headers={'Content-Type': mimetypes.guess_type(key)[0] or 'application/octet-stream', 'x-upsert': 'false'})
        if response.status_code not in (200, 201, 400, 409):
            raise unavailable()
        # Verify actual persisted bytes, including duplicate/unknown-outcome retry.
        if self.read(key) != content:
            raise Problem('雲端物件驗證失敗，原檔未覆寫', code='storage', status=503)
        return key

    def list(self, prefix):
        self.ensure_private()
        checked_key(prefix)
        result = []
        offset = 0
        while True:
            response = self._request('POST', 'object/list/'+self.bucket,
                json={'prefix': prefix.rstrip('/')+'/', 'limit': 100, 'offset': offset, 'sortBy': {'column': 'name', 'order': 'asc'}})
            if response.status_code != 200:
                raise unavailable()
            try:
                rows = response.json()
                if not isinstance(rows, list):
                    raise ValueError()
                for row in rows:
                    key = checked_key(prefix.rstrip('/')+'/'+row['name'])
                    if not row.get('id'):
                        raise ValueError('nested folders are not supported')
                    result.append(key)
            except (ValueError, KeyError, TypeError):
                raise unavailable() from None
            if len(rows) < 100:
                return result
            offset += len(rows)

    def delete_backups(self, keys):
        if any(not re.fullmatch(r'backups/\d{4}-\d{2}-\d{2}_(?:\d{6}_)?[a-f0-9]{64}\.zip', key) for key in keys):
            raise Problem('只能清理已驗證的資料庫備份')
        if not keys:
            return
        self.ensure_private()
        response = self._request('DELETE', 'object/'+self.bucket, json={'prefixes': keys})
        if response.status_code not in (200, 204):
            raise unavailable()


def storage_from_config(config):
    backend = config.get('STORAGE_BACKEND', 'local')
    if backend == 'supabase':
        return SupabaseStorage(config.get('SUPABASE_URL'), config.get('SUPABASE_SERVICE_KEY'), config.get('SUPABASE_BUCKET', 'duck-private'))
    if backend != 'local' or config.get('CLOUD_MODE'):
        raise ValueError('Cloud mode requires durable Supabase storage')
    return LocalStorage(config['DATA_DIR'])


def get_storage():
    if 'object_storage' not in current_app.extensions:
        current_app.extensions['object_storage'] = storage_from_config(current_app.config)
    return current_app.extensions['object_storage']


def send_object(key, *, attachment=False):
    storage = get_storage()
    if storage.remote:
        response = send_file(io.BytesIO(storage.read(key)), download_name=PurePosixPath(key).name, as_attachment=attachment)
    else:
        if not storage.exists(key):
            raise Problem('找不到檔案', status=404)
        response = send_file(storage.path(key), as_attachment=attachment)
    # Publication/auth can change, so private bytes must not outlive authorization.
    response.headers['Cache-Control'] = 'private, no-store'
    return response
