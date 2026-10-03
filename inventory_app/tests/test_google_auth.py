import tempfile
import time
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from joserfc import jwt
from joserfc.jwk import RSAKey

from app import create_app
from app.db import connect_db


class GoogleAuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app({'TESTING': True, 'DATA_DIR': Path(self.tmp.name),
                               'SECRET_KEY': 'test-only', 'AUTH_MODE': 'google', 'CUSTOMER_ORDERING_ENABLED': True,
                               'GOOGLE_CLIENT_ID': 'test-client', 'GOOGLE_CLIENT_SECRET': 'test-secret',
                               'GOOGLE_REDIRECT_URI': 'http://127.0.0.1:8765/auth/google/callback',
                               'GOOGLE_ADMIN_EMAIL': 'owner@gmail.com'})
        self.client = self.app.test_client()

    def login(self, client=None, email='owner@gmail.com', sub='owner-sub', **claims):
        client = client or self.client
        info = {'sub': sub, 'email': email, 'email_verified': True, 'name': '店家', **claims}
        with patch('app.google_auth.verified_identity', return_value=info):
            result = client.get('/auth/google/callback?code=test&state=test')
        self.assertEqual(result.status_code, 302)
        return client.get('/api/session').get_json()

    def post(self, path, body, client=None):
        client = client or self.client
        token = client.get('/api/session').get_json()['csrf']
        return client.post(path, json=body, headers={'X-CSRF-Token': token})

    def test_google_mode_disables_legacy_setup_and_password(self):
        state = self.client.get('/api/session').get_json()
        self.assertFalse(state['setup_required'])
        self.assertEqual(state['auth_mode'], 'google')
        self.assertTrue(state['google_ready'])
        for path in ['/api/setup', '/api/login']:
            self.assertEqual(self.post(path, {'password': 'test-password-123'}).status_code, 403)
        with self.client.session_transaction() as session:
            session['user'] = 1
        self.assertEqual(self.client.get('/api/products').status_code, 401)

    def test_only_configured_owner_can_bootstrap(self):
        self.assertFalse(self.login(email='stranger@gmail.com')['authenticated'])
        state = self.login()
        self.assertTrue(state['authenticated'])
        self.assertEqual(state['account']['role'], 'admin')
        self.assertEqual(state['account']['email'], 'owner@gmail.com')

    def test_invalid_identity_rejected(self):
        for claims in [{'email_verified': False}, {'email_verified': 'true'}, {'sub': ''}]:
            self.assertFalse(self.login(**claims)['authenticated'])

    def test_staff_invitation_revokes_existing_sessions_and_requires_owner(self):
        self.login()
        result = self.post('/api/accounts', {'email': 'Staff@gmail.com'})
        self.assertEqual(result.status_code, 201, result.get_json())
        account_id = result.get_json()['id']
        staff = self.app.test_client()
        state = self.login(staff, 'staff@gmail.com', 'staff-sub')
        self.assertEqual(state['account']['role'], 'staff')
        self.assertEqual(staff.get('/api/products').status_code, 200)
        self.assertEqual(staff.get('/api/accounts').status_code, 403)
        self.assertEqual(self.post('/api/accounts', {'email': 'other@gmail.com'}, staff).status_code, 403)
        self.assertEqual(self.post(f'/api/accounts/{account_id}', {'active': False}).status_code, 200)
        self.assertEqual(staff.get('/api/products').status_code, 401)
        self.assertFalse(self.login(staff, 'staff@gmail.com', 'staff-sub')['authenticated'])
        self.assertEqual(self.post(f'/api/accounts/{account_id}', {'active': True}).status_code, 200)
        self.assertEqual(staff.get('/api/products').status_code, 401)
        self.assertTrue(self.login(staff, 'staff@gmail.com', 'staff-sub')['authenticated'])

    def test_owner_cannot_disable_self_and_csrf_is_required(self):
        state = self.login()
        account_id = state['account']['id']
        self.assertEqual(self.post(f'/api/accounts/{account_id}', {'active': False}).status_code, 409)
        self.assertEqual(self.client.post('/api/accounts', json={'email': 'staff@gmail.com'}).status_code, 403)
        self.assertEqual(self.post('/api/accounts', {'email': 'not an email'}).status_code, 400)
        self.assertEqual(self.post('/api/accounts', {'email': 'owner@gmail.com'}).status_code, 409)

    def test_bound_identity_cannot_be_replaced_by_same_email(self):
        self.login()
        self.post('/api/logout', {})
        self.assertFalse(self.login(sub='different-google-account')['authenticated'])

    def test_session_expires_and_disabled_account_loses_photo_access(self):
        self.login()
        with self.client.session_transaction() as session:
            session['auth_expires'] = time.time() - 1
        self.assertEqual(self.client.get('/api/products').status_code, 401)
        self.login()
        conn = connect_db(self.app.config['DB_PATH'])
        conn.execute('UPDATE staff_accounts SET active=0')
        conn.close()
        self.assertEqual(self.client.get('/media/' + 'a'*64 + '.jpg').status_code, 401)

    def test_missing_config_fails_closed_and_customer_remains_public(self):
        self.app.config['GOOGLE_CLIENT_SECRET'] = ''
        self.assertFalse(self.client.get('/api/session').get_json()['google_ready'])
        self.assertEqual(self.client.get('/auth/google/start').status_code, 302)
        for path in ['/shop', '/api/shop/catalog', '/api/shop/recipes', '/api/shop/session']:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get('/api/customer-orders').status_code, 401)

    def test_callback_bad_state_is_rejected_without_provider_request(self):
        result = self.client.get('/auth/google/callback?code=fake&state=wrong')
        self.assertEqual(result.status_code, 302)
        self.assertFalse(self.client.get('/api/session').get_json()['authenticated'])

    def test_oidc_signature_claims_state_and_cookie_token_hygiene(self):
        remote = self.app.extensions['google_oidc']
        key = RSAKey.generate_key(2048, parameters={'kid': 'test-key'})
        wrong_key = RSAKey.generate_key(2048, parameters={'kid': 'test-key'})
        metadata = {'authorization_endpoint': 'https://accounts.google.com/o/oauth2/v2/auth',
                    'issuer': 'https://accounts.google.com',
                    'id_token_signing_alg_values_supported': ['RS256'],
                    'jwks': {'keys': [key.as_dict(private=False)]}}
        cases = [('valid', {}, key), ('nonce', {'nonce': 'wrong'}, key),
                 ('audience', {'aud': 'another-client'}, key),
                 ('issuer', {'iss': 'https://attacker.invalid'}, key),
                 ('expired', {'exp': int(time.time()) - 600}, key),
                 ('signature', {}, wrong_key), ('state', {}, key)]
        for name, override, signing_key in cases:
            with self.subTest(name=name), patch.object(remote, 'load_server_metadata', return_value=metadata):
                client = self.app.test_client()
                response = client.get('/auth/google/start')
                params = parse_qs(urlsplit(response.location).query)
                self.assertEqual(params['code_challenge_method'], ['S256'])
                self.assertIn('openid', params['scope'][0])
                self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])
                claims = {'iss': metadata['issuer'], 'aud': 'test-client', 'sub': 'owner-sub',
                          'email': 'owner@gmail.com', 'email_verified': True,
                          'iat': int(time.time()), 'exp': int(time.time()) + 300,
                          'nonce': params['nonce'][0], **override}
                signed = jwt.encode({'alg': 'RS256', 'kid': 'test-key'}, claims, signing_key)
                token = {'access_token': 'do-not-store-this-token', 'id_token': signed, 'token_type': 'Bearer'}
                with patch.object(remote, 'fetch_access_token', return_value=token) as exchange:
                    state = 'wrong' if name == 'state' else params['state'][0]
                    result = client.get('/auth/google/callback', query_string={'state': state, 'code': 'test-code'})
                    self.assertEqual(result.status_code, 302)
                    self.assertEqual(client.get('/api/session').get_json()['authenticated'], name == 'valid')
                    if name == 'state':
                        exchange.assert_not_called()
                    else:
                        self.assertTrue(exchange.call_args.kwargs['code_verifier'])
                    with client.session_transaction() as session:
                        self.assertNotIn('do-not-store-this-token', str(dict(session)))
                        self.assertNotIn(signed, str(dict(session)))
                    if name == 'valid':
                        self.post('/api/logout', {}, client)
                        replay = client.get('/auth/google/callback', query_string={'state': state, 'code': 'test-code'})
                        self.assertEqual(replay.status_code, 302)
                        self.assertFalse(client.get('/api/session').get_json()['authenticated'])

    def test_non_google_authoritative_email_cannot_claim_invitation(self):
        self.login()
        self.assertEqual(self.post('/api/accounts', {'email': 'staff@example.org'}).status_code, 201)
        client = self.app.test_client()
        self.assertFalse(self.login(client, 'staff@example.org', 'external-sub')['authenticated'])
        self.assertTrue(self.login(client, 'staff@example.org', 'external-sub', hd='example.org')['authenticated'])

    def test_system_admin_adds_owner_and_owner_can_only_manage_staff(self):
        admin = self.login()['account']
        added = self.post('/api/accounts', {'email': 'store-owner@gmail.com', 'role': 'owner'})
        self.assertEqual(added.status_code, 201)
        owner_id = added.get_json()['id']
        owner = self.app.test_client()
        self.assertEqual(self.login(owner, 'store-owner@gmail.com', 'store-owner')['account']['role'], 'owner')
        self.assertEqual(owner.get('/api/accounts').status_code, 200)
        for role in ['owner', 'admin']:
            self.assertEqual(self.post('/api/accounts', {'email': 'other@gmail.com', 'role': role}, owner).status_code, 403)
        self.assertEqual(self.post(f'/api/accounts/{admin["id"]}', {'active': False}, owner).status_code, 403)
        self.assertEqual(self.post(f'/api/accounts/{owner_id}', {'active': False}, owner).status_code, 403)
        result = self.post('/api/accounts', {'email': 'staff@gmail.com', 'role': 'staff'}, owner)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(self.post(f'/api/accounts/{result.get_json()["id"]}', {'active': False}, owner).status_code, 200)
        self.assertEqual(self.post(f'/api/accounts/{owner_id}', {'active': False}).status_code, 200)
        self.assertEqual(owner.get('/api/products').status_code, 401)

    def test_expired_session_can_logout_and_preserves_guest_order_recovery(self):
        self.client.get('/api/shop/session')
        with self.client.session_transaction() as session:
            client_id = session['shop_client']
        self.login()
        with self.client.session_transaction() as session:
            session['auth_expires'] = time.time() - 1
        self.assertEqual(self.post('/api/logout', {}).status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session['shop_client'], client_id)

    def test_local_auth_settings_persist_without_exposing_secret_and_env_wins(self):
        settings = {'AUTH_MODE': 'google', 'GOOGLE_ADMIN_EMAIL': 'admin@gmail.com',
                    'GOOGLE_CLIENT_ID': 'local-client', 'GOOGLE_CLIENT_SECRET': 'private-local-secret',
                    'GOOGLE_REDIRECT_URI': 'http://127.0.0.1:8765/auth/google/callback'}
        (Path(self.tmp.name)/'auth-config.json').write_text(json.dumps(settings), encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True):
            app = create_app({'TESTING': True, 'DATA_DIR': Path(self.tmp.name), 'SECRET_KEY': 'test-only'})
            response = app.test_client().get('/api/session')
            self.assertTrue(response.get_json()['google_ready'])
            self.assertNotIn('private-local-secret', response.get_data(as_text=True))
            self.assertEqual(app.config['GOOGLE_ADMIN_EMAIL'], 'admin@gmail.com')
        with patch.dict(os.environ, {'AUTH_MODE': 'password'}):
            app = create_app({'TESTING': True, 'DATA_DIR': Path(self.tmp.name), 'SECRET_KEY': 'test-only'})
            self.assertEqual(app.config['AUTH_MODE'], 'password')


if __name__ == '__main__':
    unittest.main()
