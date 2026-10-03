import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import create_app


class CloudBootstrapTest(unittest.TestCase):
    def test_cloud_server_uses_only_nearest_forwarded_ip(self):
        import cloud
        from waitress.proxy_headers import proxy_headers_middleware
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        options = {}
        with patch.object(cloud, 'create_app'), patch.object(cloud, 'serve', side_effect=lambda app, **kw: options.update(kw)):
            cloud.main()
        seen = []
        def endpoint(environ, start_response):
            seen.append(environ.copy())
            return Response('ok')(environ, start_response)
        client = Client(proxy_headers_middleware(endpoint,
            trusted_proxy=options.get('trusted_proxy'),
            trusted_proxy_count=options.get('trusted_proxy_count', 1),
            trusted_proxy_headers=options.get('trusted_proxy_headers')), Response)
        for ip in ('198.51.100.1', '198.51.100.2'):
            client.get('/', environ_overrides={'REMOTE_ADDR': '169.254.1.1'}, headers={
                'X-Forwarded-For': '203.0.113.99, '+ip,
                'X-Forwarded-Host': 'attacker.example', 'X-Forwarded-Proto': 'http'})
        self.assertEqual([e['REMOTE_ADDR'] for e in seen], ['198.51.100.1', '198.51.100.2'])
        self.assertNotIn('HTTP_X_FORWARDED_HOST', seen[0])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = dict(TESTING=True, CLOUD_MODE=True, DATA_DIR=Path(self.tmp.name),
                           DATABASE_URL='postgresql://runtime:secret@db.example:5432/postgres?sslmode=require',
                           DATABASE_SCHEMA='duck', STORAGE_BACKEND='supabase',
                           SUPABASE_URL='https://test.supabase.co', SUPABASE_SERVICE_KEY='test-key',
                           SUPABASE_BUCKET='duck-private', SECRET_KEY='a' * 64,
                           AUTH_MODE='google', GOOGLE_CLIENT_ID='client', GOOGLE_CLIENT_SECRET='secret',
                           GOOGLE_ADMIN_EMAIL='admin@gmail.com',
                           GOOGLE_REDIRECT_URI='https://duck.example/auth/google/callback')

    def test_incomplete_cloud_never_creates_local_database(self):
        for key in ('DATABASE_URL', 'SECRET_KEY', 'SUPABASE_URL', 'SUPABASE_SERVICE_KEY',
                    'GOOGLE_CLIENT_SECRET', 'GOOGLE_ADMIN_EMAIL'):
            with self.subTest(key=key), patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValueError):
                    create_app({**self.config, key: ''})
                self.assertFalse((self.config['DATA_DIR'] / 'inventory.sqlite3').exists())

    def test_cloud_rejects_unsafe_configuration(self):
        for key, value in (('DATABASE_URL', 'local.sqlite3'), ('STORAGE_BACKEND', 'local'),
                           ('GOOGLE_REDIRECT_URI', 'http://localhost/auth/google/callback'),
                           ('SECRET_KEY', 'short'), ('AUTH_MODE', 'password'),
                           ('DATABASE_SCHEMA', 'public')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                create_app({**self.config, key: value})

    def test_cloud_ignores_local_credentials_and_does_not_initialize_schema(self):
        (self.config['DATA_DIR'] / 'auth-config.json').write_text('invalid json', encoding='utf-8')
        with patch('app.connect_db') as connect, patch('app.init_db') as initialize:
            app = create_app(self.config)
        connect.assert_not_called()
        initialize.assert_not_called()
        self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
        self.assertFalse((self.config['DATA_DIR'] / 'secret.key').exists())

    def test_health_checks_db_without_exposing_details(self):
        with patch('app.connect_db'):
            app = create_app(self.config)
        with patch('app.get_db') as db:
            db.return_value.execute.return_value.fetchone.return_value = [1]
            response = app.test_client().get('/health')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {'status': 'ok'})
        import sqlite3
        with patch('app.get_db', side_effect=sqlite3.OperationalError('secret dsn')):
            response = app.test_client().get('/health')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('secret', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
