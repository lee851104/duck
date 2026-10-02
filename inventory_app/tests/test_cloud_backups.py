import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from app.common import Problem
from tests.test_cloud_storage import StorageServer


class CloudBackupTest(unittest.TestCase):
    def setUp(self):
        self.server = StorageServer()
        self.mock = patch('requests.Session.request', side_effect=self.server.request)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.config = {'CLOUD_MODE': True, 'STORAGE_BACKEND': 'supabase',
            'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_SERVICE_KEY': 'sb_secret_fixture-only',
            'SUPABASE_BUCKET': 'duck-private', 'DATABASE_URL': 'postgresql://test:private-password@localhost/test?sslmode=verify-full', 'DATABASE_SCHEMA': 'duck'}

    def dump(self, config, destination):
        Path(destination).write_bytes(b'PGDMP-test-consistent-snapshot')

    def test_manifest_verified_and_only_seven_daily_backups_retained(self):
        from app.backups import create_cloud_backup
        self.server.objects['media/old.jpg'] = b'old-picture'
        self.server.objects['exports/old.xlsx'] = b'old-export'
        for day in range(1, 10):
            self.server.objects[f'backups/2000-01-{day:02}_'+('a'*64)+'.zip'] = b'old-backup'
        with patch('app.backups.dump_postgres', side_effect=self.dump):
            result = create_cloud_backup(self.config)
        archives = [k for k in self.server.objects if k.startswith('backups/')]
        self.assertEqual(len(archives), 7)
        self.assertEqual(self.server.objects['media/old.jpg'], b'old-picture')
        self.assertEqual(self.server.objects['exports/old.xlsx'], b'old-export')
        with ZipFile(io.BytesIO(self.server.objects[result['path']])) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['format'], 'duck-postgres-backup-v1')
            self.assertEqual(manifest['schema'], 'duck')
            self.assertEqual(manifest['database']['sha256'], hashlib.sha256(archive.read('database.dump')).hexdigest())
            self.assertEqual(manifest['objects']['media/old.jpg']['sha256'], hashlib.sha256(b'old-picture').hexdigest())
            self.assertEqual(manifest['objects']['exports/old.xlsx']['size'], 10)
            self.assertNotIn('private-password', archive.read('manifest.json').decode())

    def test_failed_dump_does_not_publish_or_prune_backups(self):
        from app.backups import create_cloud_backup
        self.server.objects['media/old.jpg'] = b'old-picture'
        with patch('app.backups.dump_postgres', side_effect=Problem('dump failure')):
            with self.assertRaises(Problem):
                create_cloud_backup(self.config)
        self.assertEqual(list(self.server.objects), ['media/old.jpg'])

    def test_backup_archive_validation_rejects_corruption(self):
        from app.backups import validate_cloud_backup
        stream = io.BytesIO()
        with ZipFile(stream, 'w') as archive:
            archive.writestr('database.dump', b'broken')
            archive.writestr('manifest.json', json.dumps({'format': 'duck-postgres-backup-v1', 'schema': 'duck', 'database': {'sha256': 'wrong'}, 'objects': {}}))
        with self.assertRaises(Problem):
            validate_cloud_backup(stream.getvalue())

    def test_cloud_worker_cannot_start_daemon(self):
        from app.backups import start_backup_worker
        class App:
            config = {'CLOUD_MODE': True}
        with self.assertRaises(ValueError):
            start_backup_worker(App())

class CloudRestoreBundleTest(unittest.TestCase):
    setUp = CloudBackupTest.setUp
    dump = CloudBackupTest.dump
    def test_verified_bundle_download_restores_original_objects(self):
        from app.backups import create_cloud_backup
        from tools.cloud_backup import download_bundle
        from app.storage import storage_from_config
        self.server.objects['media/old.jpg'] = b'old-picture'
        with patch('app.backups.dump_postgres', side_effect=self.dump):
            result = create_cloud_backup(self.config)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'restore'
            download_bundle(storage_from_config(self.config), result['path'], target)
            self.assertEqual((target/'media/old.jpg').read_bytes(), b'old-picture')
            self.assertTrue((target/'database.dump').read_bytes().startswith(b'PGDMP'))
            with self.assertRaises(Problem):
                download_bundle(storage_from_config(self.config), result['path'], target)
            self.server.objects['media/old.jpg'] = b'corrupt'
            broken = Path(tmp)/'broken'
            with self.assertRaises(Problem):
                download_bundle(storage_from_config(self.config), result['path'], broken)
            self.assertFalse(broken.exists())

class CloudBackupQueueTest(unittest.TestCase):
    def setUp(self):
        from app.db import connect_db, init_db
        from types import SimpleNamespace
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name)/'test.sqlite'
        self.conn = connect_db(self.db)
        self.addCleanup(self.conn.close)
        init_db(self.conn)
        self.resource = 'projects/test-project/locations/asia-southeast1/jobs/duck-backup'
        self.app = SimpleNamespace(config={'CLOUD_MODE': True, 'DATABASE_URL': str(self.db), 'BACKUP_JOB_RESOURCE': self.resource})
        self.posts = 0
        self.post_status = 200
        self.unknown = False
        self.operation = 'projects/test-project/locations/asia-southeast1/operations/op-1'
        self.patch = patch('requests.request', side_effect=self.remote)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def remote(self, method, url, **kwargs):
        import requests
        self.assertFalse(kwargs['allow_redirects'])
        self.assertLessEqual(sum(kwargs['timeout']), 15)
        response = requests.Response()
        response.status_code = 200
        if method == 'GET':
            self.assertEqual(url, 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token')
            self.assertEqual(kwargs['headers'], {'Metadata-Flavor': 'Google'})
            response._content = json.dumps({'access_token': 'fixture-token', 'token_type': 'Bearer', 'expires_in': 300}).encode()
        elif method == 'POST':
            self.assertEqual(url, 'https://run.googleapis.com/v2/'+self.resource+':run')
            self.assertEqual(kwargs['headers']['Authorization'], 'Bearer fixture-token')
            self.assertEqual(kwargs['json'], {})
            self.posts += 1
            if self.unknown:
                raise requests.Timeout('fixture-token must not leak')
            response.status_code = self.post_status
            response._content = json.dumps({'name': self.operation, 'done': False}).encode()
        else:
            raise AssertionError('Unexpected remote call')
        return response

    def test_queue_persists_pending_and_rejects_second_request(self):
        from app.backups import enqueue_cloud_backup
        self.assertEqual(enqueue_cloud_backup(self.app, self.conn), {'queued': True})
        pending = json.loads(self.conn.execute("SELECT value FROM metadata WHERE key='cloud_backup_pending'").fetchone()[0])
        self.assertEqual(pending['operation'], self.operation)
        self.assertNotIn('fixture-token', json.dumps(pending))
        with self.assertRaises(Problem) as error:
            enqueue_cloud_backup(self.app, self.conn)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.posts, 1)

    def test_unknown_post_outcome_remains_blocked_and_sanitized(self):
        from app.backups import enqueue_cloud_backup
        self.unknown = True
        with self.assertRaises(Problem) as error:
            enqueue_cloud_backup(self.app, self.conn)
        self.assertEqual(error.exception.status, 503)
        self.assertNotIn('fixture-token', str(error.exception))
        self.assertIsNotNone(self.conn.execute("SELECT value FROM metadata WHERE key='cloud_backup_pending'").fetchone())
        with self.assertRaises(Problem) as error:
            enqueue_cloud_backup(self.app, self.conn)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.posts, 1)

    def test_definite_rejection_allows_retry(self):
        from app.backups import enqueue_cloud_backup
        self.post_status = 403
        with self.assertRaises(Problem):
            enqueue_cloud_backup(self.app, self.conn)
        self.assertIsNone(self.conn.execute("SELECT value FROM metadata WHERE key='cloud_backup_pending'").fetchone())
        self.post_status = 200
        self.assertEqual(enqueue_cloud_backup(self.app, self.conn), {'queued': True})

    def test_invalid_resource_rejected_before_network(self):
        from app.backups import enqueue_cloud_backup
        for resource in ('https://evil.invalid/run', self.resource+'/../other', self.resource+'?redirect=evil'):
            self.app.config['BACKUP_JOB_RESOURCE'] = resource
            with self.assertRaises(Problem):
                enqueue_cloud_backup(self.app, self.conn)
        self.assertEqual(self.posts, 0)

    def test_worker_records_result_and_clears_its_pending_intent(self):
        from app.backups import enqueue_cloud_backup, perform_backup
        enqueue_cloud_backup(self.app, self.conn)
        with patch('app.backups.create_cloud_backup', return_value={'path': 'backups/fixture.zip', 'filename': 'fixture.zip'}):
            self.assertEqual(perform_backup(self.app), {'filename': 'fixture.zip'})
        self.assertIsNone(self.conn.execute("SELECT value FROM metadata WHERE key='cloud_backup_pending'").fetchone())
        self.assertEqual(self.conn.execute('SELECT path FROM backup_runs').fetchone()[0], 'backups/fixture.zip')

    def test_worker_failure_records_error_and_releases_intent(self):
        from app.backups import enqueue_cloud_backup, perform_backup
        enqueue_cloud_backup(self.app, self.conn)
        with patch('app.backups.create_cloud_backup', side_effect=Problem('fixture failure')):
            with self.assertRaises(Problem):
                perform_backup(self.app)
        self.assertIsNone(self.conn.execute("SELECT value FROM metadata WHERE key='cloud_backup_pending'").fetchone())
        self.assertIsNotNone(self.conn.execute('SELECT error FROM backup_runs').fetchone()[0])

    def test_metadata_failure_releases_intent_without_launching_job(self):
        from app.backups import enqueue_cloud_backup
        import requests
        with patch('requests.request', side_effect=requests.Timeout('fixture-token')):
            with self.assertRaises(Problem) as error:
                enqueue_cloud_backup(self.app, self.conn)
        self.assertNotIn('fixture-token', str(error.exception))
        self.assertIsNone(self.conn.execute("SELECT value FROM metadata WHERE key='cloud_backup_pending'").fetchone())
        self.assertEqual(self.posts, 0)

    def test_old_worker_cannot_clear_new_intent(self):
        from app.backups import enqueue_cloud_backup, perform_backup
        enqueue_cloud_backup(self.app, self.conn)
        def complete(config):
            self.conn.execute("UPDATE metadata SET value=? WHERE key='cloud_backup_pending'", (json.dumps({'id': 'new-intent'}),))
            return {'path': 'backups/fixture.zip', 'filename': 'fixture.zip'}
        with patch('app.backups.create_cloud_backup', side_effect=complete):
            perform_backup(self.app)
        pending = json.loads(self.conn.execute("SELECT value FROM metadata WHERE key='cloud_backup_pending'").fetchone()[0])
        self.assertEqual(pending['id'], 'new-intent')


class CloudBackupQueueRouteTest(unittest.TestCase):
    def test_cloud_button_is_authenticated_async_and_reports_pending(self):
        from tests import test_app
        test_app.AppTest.setUp(self)
        self.login = lambda: test_app.AppTest.login(self)
        self.login()
        self.app.config.update(CLOUD_MODE=True, BACKUP_JOB_RESOURCE='projects/test-project/locations/asia-southeast1/jobs/duck-backup')
        from app.backups import enqueue_cloud_backup
        operation = {'name': 'projects/test-project/locations/asia-southeast1/operations/op-1'}
        import requests
        token = requests.Response(); token.status_code = 200; token._content = b'{"access_token":"fixture-token"}'
        started = requests.Response(); started.status_code = 200; started._content = json.dumps(operation).encode()
        with patch('requests.request', side_effect=[token, started]):
            self.assertEqual(self.app.test_client().post('/api/backups').status_code, 401)
            response = self.client.post('/api/backups', headers={'X-CSRF-Token': self.token})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json, {'queued': True})
        self.assertTrue(self.client.get('/api/meta').json['backup_pending'])
        # The pending intent also survives request teardown.
        from app.db import connect_db
        conn = connect_db(self.app.config['DB_PATH'])
        self.addCleanup(conn.close)
        self.assertIsNotNone(conn.execute("SELECT value FROM metadata WHERE key='cloud_backup_pending'").fetchone())
