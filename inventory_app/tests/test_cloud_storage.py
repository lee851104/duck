import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import requests
from PIL import Image

from app.common import Problem
from app.db import connect_db
from tests import test_app


class StorageServer:
    """Stateful external HTTP boundary; application storage code stays real."""
    def __init__(self):
        self.objects = {}
        self.fail = False
        self.public = False

    def request(self, method, url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{}'
        if self.fail:
            response.status_code = 503
            return response
        path = unquote(url.split('/storage/v1/')[1])
        if path.startswith('bucket/'):
            response._content = json.dumps({'public': self.public}).encode()
        elif path.startswith('object/list/'):
            data = kwargs['json']
            prefix = data['prefix'].rstrip('/') + '/'
            names = sorted(k[len(prefix):] for k in self.objects if k.startswith(prefix))
            response._content = json.dumps([{'name': n, 'id': n, 'metadata': {}} for n in names[data['offset']:data['offset']+data['limit']]]).encode()
        elif method == 'DELETE':
            for key in kwargs['json']['prefixes']:
                self.objects.pop(key, None)
        else:
            key = path.split('/', 2)[2]
            if method == 'POST':
                if key in self.objects:
                    response.status_code = 409
                else:
                    self.objects[key] = kwargs['data']
            elif key in self.objects:
                response._content = self.objects[key]
            else:
                response.status_code = 404
        return response


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.server = StorageServer()
        self.mock = patch('requests.Session.request', side_effect=self.server.request)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def client(self):
        from app.storage import SupabaseStorage
        return SupabaseStorage('https://example.supabase.co', 'sb_secret_fixture-only', 'duck-private')

    def test_remote_roundtrip_fresh_client_and_retry(self):
        name = hashlib.sha256(b'photo').hexdigest()+'.jpg'
        self.client().put('media/'+name, b'photo')
        self.client().put('media/'+name, b'photo')
        self.assertEqual(self.client().read('media/'+name), b'photo')
        self.assertEqual(len(self.server.objects), 1)

    def test_failure_does_not_become_missing_or_success(self):
        self.server.fail = True
        for action in (lambda: self.client().read('media/a.jpg'), lambda: self.client().exists('media/a.jpg'), lambda: self.client().put('media/a.jpg', b'a')):
            with self.assertRaises(Problem) as error:
                action()
            self.assertEqual(error.exception.status, 503)
            self.assertNotIn('sb_secret_fixture-only', str(error.exception))

    def test_public_bucket_refused(self):
        self.server.public = True
        with self.assertRaises(Problem):
            self.client().put('media/a.jpg', b'a')
        self.assertFalse(self.server.objects)

    def test_missing_object_and_conflicting_content(self):
        self.assertFalse(self.client().exists('media/missing.jpg'))
        with self.assertRaises(Problem) as error:
            self.client().read('media/missing.jpg')
        self.assertEqual(error.exception.status, 404)
        self.client().put('exports/one.xlsx', b'a')
        with self.assertRaises(Problem):
            self.client().put('exports/one.xlsx', b'b')
        self.assertEqual(self.client().read('exports/one.xlsx'), b'a')

    def test_local_storage_rejects_traversal(self):
        from app.storage import LocalStorage
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            for key in ('../escape', 'media/../../escape', 'media\\escape', '/absolute'):
                with self.assertRaises(Problem):
                    storage.put(key, b'bad')


class RemoteRoutesTest(unittest.TestCase):
    login = test_app.AppTest.login

    def setUp(self):
        test_app.AppTest.setUp(self)
        self.app.config['SOURCE_DIR'] = self.app.config['DATA_DIR']/'empty-source'
        self.login()
        self.server = StorageServer()
        self.mock = patch('requests.Session.request', side_effect=self.server.request)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.app.config.update(STORAGE_BACKEND='supabase', SUPABASE_URL='https://example.supabase.co', SUPABASE_SERVICE_KEY='sb_secret_fixture-only', SUPABASE_BUCKET='duck-private')
        self.headers = {'X-CSRF-Token': self.token}
        self.conn = connect_db(self.app.config['DB_PATH'])
        self.addCleanup(self.conn.close)

    def test_upload_and_authorized_proxy_survive_local_file_loss(self):
        import base64
        image = io.BytesIO()
        Image.new('RGB', (10, 10), 'blue').save(image, 'PNG')
        result = self.client.post('/api/shop-admin/photo', json={'data': base64.b64encode(image.getvalue()).decode()}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        name = result.json['image']
        self.assertIn('media/'+name, self.server.objects)
        self.assertFalse((self.app.config['DATA_DIR']/'media'/name).exists())
        self.app.extensions.pop('object_storage', None)
        self.assertEqual(self.client.get('/media/'+name).data, self.server.objects['media/'+name])
        guest = self.app.test_client()
        self.assertEqual(guest.get('/media/'+name).status_code, 401)
        self.assertEqual(guest.get('/shop/media/'+name).status_code, 404)
        self.conn.execute("INSERT INTO recipes(slug,name,description,theme,tag,notes,steps,published,image) VALUES('test','test','','soup','','','',1,?)", (name,))
        self.assertEqual(guest.get('/shop/media/'+name).data, self.server.objects['media/'+name])
        self.server.fail = True
        self.assertEqual(guest.get('/shop/media/'+name).status_code, 503)

    def test_export_remote_and_failed_upload_rolls_back_export_record(self):
        self.conn.execute("INSERT INTO invoice_items(source,category,code,name,price,unit,tax,kind,fixed) VALUES('test','1','01','test','20','包',1,0,1)")
        result = self.client.post('/api/invoice-exports', headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertIn('exports/'+result.json['filename'], self.server.objects)
        self.assertFalse((self.app.config['DATA_DIR']/'exports'/result.json['filename']).exists())
        self.app.extensions.pop('object_storage', None)
        response = self.client.get('/api/invoice-exports/'+result.json['export_id']+'/download')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b'PK'))
        self.server.fail = True
        self.assertEqual(self.client.post('/api/invoice-exports', headers=self.headers).status_code, 503)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM invoice_exports').fetchone()[0], 1)

    def test_cloud_original_import_disabled(self):
        self.app.config['CLOUD_MODE'] = True
        for path in ('/api/imports/preview', '/api/imports/'+'a'*64+'/commit'):
            response = self.client.post(path, json={}, headers=self.headers)
            self.assertEqual(response.status_code, 409)
            self.assertIn('本機', response.json['error']['message'])

class MediaMigrationTest(unittest.TestCase):
    setUp = StorageTest.setUp
    client = StorageTest.client
    def test_migration_preserves_names_verifies_bytes_and_resumes(self):
        from tools.migrate_media import migrate_media
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp)/'media'
            media.mkdir()
            (media/('a'*64+'.thumb.jpg')).write_bytes(b'thumbnail')
            manifest = Path(tmp)/'manifest.json'
            result = migrate_media(media, self.client(), manifest)
            self.assertEqual(result['count'], 1)
            self.assertEqual(result['bytes'], 9)
            result = migrate_media(media, self.client(), manifest)
            self.assertEqual(result['count'], 1)
            self.assertEqual(len(self.server.objects), 1)
            self.server.objects['media/'+'a'*64+'.thumb.jpg'] = b'corrupt'
            with self.assertRaises(Problem):
                migrate_media(media, self.client(), manifest)

    def test_migration_includes_historical_invoice_exports(self):
        from tools.migrate_media import migrate_media
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp)/'media'
            exports = Path(tmp)/'exports'
            media.mkdir()
            exports.mkdir()
            (exports/'易發票商品_abc123.xlsx').write_bytes(b'xlsx-history')
            result = migrate_media(media, self.client(), Path(tmp)/'manifest.json', exports_dir=exports)
            self.assertEqual(self.client().read('exports/易發票商品_abc123.xlsx'), b'xlsx-history')
            self.assertEqual(result['count'], 1)

class StorageKeyHeadersTest(unittest.TestCase):
    @staticmethod
    def legacy_key(role):
        import base64
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=').decode()
        return encode({'alg': 'HS256', 'typ': 'JWT'})+'.'+encode({'role': role})+'.fixture-signature'

    def prepared_headers(self, key):
        from app.storage import SupabaseStorage
        storage = SupabaseStorage('https://example.supabase.co', key)
        return storage.session.prepare_request(requests.Request('GET', storage.base+'bucket/duck-private')).headers

    def test_new_secret_uses_only_apikey(self):
        key = 'sb_secret_fixture-only-not-real'
        headers = self.prepared_headers(key)
        self.assertEqual(headers['apikey'], key)
        self.assertNotIn('Authorization', headers)

    def test_legacy_service_role_jwt_keeps_both_headers(self):
        key = self.legacy_key('service_role')
        headers = self.prepared_headers(key)
        self.assertEqual(headers['apikey'], key)
        self.assertEqual(headers['Authorization'], 'Bearer '+key)

    def test_public_and_invalid_keys_rejected_without_echo(self):
        from app.storage import SupabaseStorage
        for key in ('sb_publishable_fixture-only', self.legacy_key('anon'), self.legacy_key('authenticated'), 'sb_secret_', 'invalid-key', 'sb_secret_fixture\r\nInjected: value'):
            with self.subTest(kind=key.split('_')[0]):
                with self.assertRaises(ValueError) as error:
                    SupabaseStorage('https://example.supabase.co', key)
                self.assertNotIn(key, str(error.exception))
