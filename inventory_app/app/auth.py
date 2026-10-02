import secrets
import time

from flask import Blueprint, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .common import Problem, required_text, transaction
from .db import get_db
from .google_auth import google_mode, google_ready, public_account, validate_merchant_session

auth = Blueprint('auth', __name__)


def session_data():
    session.setdefault('csrf', secrets.token_urlsafe(32))
    return {'authenticated': bool(session.get('user')), 'csrf': session['csrf'],
            'setup_required': not google_mode() and not bool(get_db().execute('SELECT 1 FROM users').fetchone()),
            'auth_mode': current_app.config['AUTH_MODE'], 'google_ready': bool(google_ready()),
            'account': public_account(g.account) if g.account else None,
            'login_error': session.pop('login_error', None)}


@auth.get('/api/session')
def state():
    return jsonify(session_data())


@auth.post('/api/setup')
def setup():
    if google_mode():
        raise Problem('請使用 Google 帳號登入', status=403)
    password = required_text(request.get_json().get('password'), '密碼', 128)
    if len(password) < 10:
        raise Problem('密碼至少需要 10 個字元')
    conn = get_db()
    with transaction(conn):
        if conn.execute('SELECT 1 FROM users').fetchone():
            raise Problem('帳號已建立，請登入', status=409)
        conn.execute('INSERT INTO users VALUES(1,?)', (generate_password_hash(password),))
    session.clear()
    session['user'] = 1
    return jsonify(session_data())


@auth.post('/api/login')
def login():
    if google_mode():
        raise Problem('請使用 Google 帳號登入', status=403)
    bucket = current_app.extensions.setdefault('login_attempts', {})
    key = request.remote_addr or 'local'
    attempts = [t for t in bucket.get(key, []) if time.monotonic()-t < 300]
    bucket[key] = attempts
    if len(attempts) >= 5:
        raise Problem('嘗試次數過多，請五分鐘後再試', status=429)
    user = get_db().execute('SELECT * FROM users WHERE id=1').fetchone()
    password = (request.get_json() or {}).get('password', '')
    if not isinstance(password, str) or not user or not check_password_hash(user['password_hash'], password):
        attempts.append(time.monotonic())
        raise Problem('密碼不正確', status=401)
    bucket.pop(key, None)
    session.clear()
    session['user'] = 1
    return jsonify(session_data())


@auth.post('/api/logout')
def logout():
    shop_client = session.get('shop_client')
    session.clear()
    if shop_client:
        session['shop_client'] = shop_client
    g.account = None
    return jsonify(session_data())


def guard():
    validate_merchant_session()
    if not request.path.startswith('/api/'):
        return
    if request.path.startswith('/api/shop/'):
        request.max_content_length = 64 * 1024
    public = {'/api/session', '/api/login', '/api/setup', '/api/logout'}
    public |= {'/api/shop/session','/api/shop/catalog','/api/shop/recipes','/api/shop/quote','/api/shop/orders','/api/shop/order-status','/api/shop/recover-order'}
    if request.path not in public and not session.get('user'):
        raise Problem('請先登入', status=401)
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        expected = session.get('csrf', '')
        if not expected or not secrets.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
            raise Problem('操作驗證已過期，請重新整理畫面', status=403)
        if request.is_json and not isinstance(request.get_json(silent=True), dict):
            raise Problem('請提供正確的表單資料')
