import tempfile
import unittest
from pathlib import Path

from app import create_app


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app({'TESTING': True, 'DATA_DIR': Path(self.tmp.name),
                               'SECRET_KEY': 'test-only', 'TODAY': '2026-10-01'})
        self.client = self.app.test_client()

    def login(self):
        state = self.client.get('/api/session').get_json()
        token = state['csrf']
        result = self.client.post('/api/setup', json={'password': 'test-password-123'},
                                  headers={'X-CSRF-Token': token})
        self.assertEqual(result.status_code, 200, result.get_json())
        self.token = result.get_json()['csrf']

    def test_login_required(self):
        self.assertEqual(self.client.get('/api/products').status_code, 401)

    def test_csrf_rejected(self):
        self.login()
        self.assertEqual(self.client.post('/api/products', json={}).status_code, 403)

    def test_setup_cannot_replace_existing_account(self):
        self.login()
        result = self.client.post('/api/setup', json={'password': 'replacement-password'},
                                  headers={'X-CSRF-Token': self.token})
        self.assertEqual(result.status_code, 409)

    def test_login_throttles_wrong_passwords(self):
        self.login()
        self.client.post('/api/logout', headers={'X-CSRF-Token': self.token})
        token = self.client.get('/api/session').get_json()['csrf']
        results = [self.client.post('/api/login', json={'password': 'wrong'},
                    headers={'X-CSRF-Token': token}).status_code for _ in range(7)]
        self.assertIn(429, results)

    def test_product_invalid_decimal_rejected(self):
        self.login()
        for price in ['NaN', 'Infinity', '-1']:
            result = self.client.post('/api/products', json={
                'name': '測試商品', 'code': 'T1', 'unit': '包', 'price': price},
                headers={'X-CSRF-Token': self.token})
            self.assertEqual(result.status_code, 400)
