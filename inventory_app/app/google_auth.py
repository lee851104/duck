"""Google OIDC login and the merchant allowlist; customers remain anonymous."""
import re
import secrets
import time
from urllib.parse import urlsplit

from authlib.common.errors import AuthlibBaseError
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, current_app, g, jsonify, redirect, request, session
from joserfc.errors import JoseError
from requests.exceptions import RequestException

from .common import Problem, now, required_text, transaction
from .db import get_db

google_auth = Blueprint('google_auth', __name__)


def google_mode():
    return current_app.config['AUTH_MODE'] == 'google'


def normalize_email(value):
    email = required_text(value, 'Google Email', 254).strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise Problem('請填寫有效的 Google Email')
    return email


def init_google(app):
    if app.config['AUTH_MODE'] not in {'password', 'google'}:
        raise ValueError('AUTH_MODE must be password or google')
    oauth = OAuth(app)
    oauth.register('google', client_id=app.config.get('GOOGLE_CLIENT_ID'),
                   client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
                   server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                   client_kwargs={'scope': 'openid email profile',
                                  'code_challenge_method': 'S256', 'timeout': 10})
    app.extensions['google_oidc'] = oauth.create_client('google')
    if app.config['AUTH_MODE'] == 'google':
        # A top-level GET from Google must carry the state cookie back.
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        uri = app.config.get('GOOGLE_REDIRECT_URI', '')
        parsed = urlsplit(uri)
        if uri and (parsed.path != '/auth/google/callback' or parsed.query or parsed.fragment
                    or parsed.username or parsed.password or not parsed.hostname
                    or (parsed.scheme != 'https' and not (
                        parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}))):
            raise ValueError('GOOGLE_REDIRECT_URI must use HTTPS (HTTP allowed only on localhost) and /auth/google/callback')
        if parsed.scheme == 'https':
            app.config['SESSION_COOKIE_SECURE'] = True


def google_ready():
    return google_mode() and all(current_app.config.get(k) for k in (
        'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI', 'GOOGLE_ADMIN_EMAIL'))


def validate_merchant_session():
    """Recheck database on every request, including private image requests."""
    g.account = None
    if not session.get('user'):
        return
    if google_mode():
        account = get_db().execute('SELECT * FROM staff_accounts WHERE id=?',
                                   (session.get('account_id'),)).fetchone()
        if (session.get('auth_method') == 'google' and account and account['active']
                and account['version'] == session.get('account_version')
                and session.get('user') == f"google:{account['id']}"
                and session.get('auth_expires', 0) > time.time()):
            g.account = dict(account)
            return
    elif session.get('auth_method') != 'google':
        return
    for key in ('user', 'account_id', 'account_version', 'auth_method', 'auth_expires'):
        session.pop(key, None)


def public_account(account):
    return {k: account[k] for k in ('id', 'email', 'name', 'role', 'active', 'last_login')}


def login_error(message):
    session['login_error'] = message
    return redirect('/')


@google_auth.get('/auth/google/start')
def start():
    if not google_ready():
        return login_error('Google 登入尚未設定完成，請聯絡店家管理員。')
    try:
        return current_app.extensions['google_oidc'].authorize_redirect(
            current_app.config['GOOGLE_REDIRECT_URI'], prompt='select_account')
    except (AuthlibBaseError, RequestException, ValueError):
        return login_error('暫時無法連線 Google，請稍後重試。')


def verified_identity():
    # Authlib validates state, signature, issuer, audience, expiry and nonce.
    token = current_app.extensions['google_oidc'].authorize_access_token()
    return token.get('userinfo') or {}


def identify_account(info):
    sub = info.get('sub')
    if info.get('email_verified') is not True or not isinstance(sub, str) or not sub or len(sub) > 255:
        raise Problem('無法確認 Google 帳號身分，請重新登入。', status=403)
    email = normalize_email(info.get('email'))
    conn = get_db()
    with transaction(conn):
        account = conn.execute('SELECT * FROM staff_accounts WHERE google_sub=?', (sub,)).fetchone()
        if account is None:
            # Only Google-authoritative email may claim a not-yet-bound invitation.
            if not (email.endswith('@gmail.com') or info.get('hd')):
                raise Problem('請使用 Gmail 或已驗證的 Google Workspace 帳號。', status=403)
            account = conn.execute('SELECT * FROM staff_accounts WHERE lower(email)=lower(?)', (email,)).fetchone()
            if account is None and email == normalize_email(current_app.config['GOOGLE_ADMIN_EMAIL']):
                if not conn.execute("SELECT 1 FROM staff_accounts WHERE role='admin'").fetchone():
                    conn.execute("INSERT INTO staff_accounts(email,role,created_at) VALUES(?,'admin',?)", (email, now()))
                    account = conn.execute('SELECT * FROM staff_accounts WHERE lower(email)=lower(?)', (email,)).fetchone()
            if account is None or account['google_sub'] is not None:
                raise Problem('此帳號沒有店家管理權限，請聯絡老闆。', status=403)
        if not account['active']:
            raise Problem('此帳號已停用，請聯絡老闆。', status=403)
        name = str(info.get('name') or email)[:100]
        conn.execute('UPDATE staff_accounts SET google_sub=?,name=?,last_login=? WHERE id=?',
                     (sub, name, now(), account['id']))
        return dict(conn.execute('SELECT * FROM staff_accounts WHERE id=?', (account['id'],)).fetchone())


@google_auth.get('/auth/google/callback')
def callback():
    if not google_ready():
        return login_error('Google 登入尚未設定完成，請聯絡店家管理員。')
    try:
        account = identify_account(verified_identity())
    except Problem as error:
        return login_error(error.message)
    except (AuthlibBaseError, JoseError, RequestException, ValueError, KeyError):
        return login_error('Google 登入未完成或已過期，請重新登入。')
    # Do not retain provider access/ID tokens in Flask's signed (readable) cookie.
    shop_client = session.get('shop_client')
    session.clear()
    if shop_client:
        session['shop_client'] = shop_client
    session.update(user=f"google:{account['id']}", auth_method='google', account_id=account['id'],
                   account_version=account['version'], auth_expires=time.time() + 8*60*60,
                   csrf=secrets.token_urlsafe(32))
    return redirect('/')


def require_account_manager():
    if not google_mode() or not g.account or g.account['role'] not in {'admin', 'owner'}:
        raise Problem('只有系統管理員或老闆可以管理登入帳號', status=403)


@google_auth.get('/api/accounts')
def list_accounts():
    require_account_manager()
    rows = get_db().execute("SELECT * FROM staff_accounts ORDER BY role='admin' DESC,role='owner' DESC,active DESC,email")
    return jsonify(items=[public_account(dict(row)) for row in rows])


@google_auth.post('/api/accounts')
def add_account():
    require_account_manager()
    email = normalize_email(request.get_json().get('email'))
    role = request.get_json().get('role', 'staff')
    allowed = {'owner', 'staff'} if g.account['role'] == 'admin' else {'staff'}
    if not isinstance(role, str) or role not in allowed:
        raise Problem('沒有新增這種角色的權限', status=403)
    conn = get_db()
    with transaction(conn):
        if conn.execute('SELECT 1 FROM staff_accounts WHERE lower(email)=lower(?)', (email,)).fetchone():
            raise Problem('這個帳號已在清單中，請直接啟用或停用', status=409)
        cursor = conn.execute('INSERT INTO staff_accounts(email,role,created_at) VALUES(?,?,?)', (email, role, now()))
        account_id = cursor.lastrowid
        conn.execute('INSERT INTO account_events(account_id,actor,action,created_at) VALUES(?,?,?,?)',
                     (account_id, session['user'], 'add:' + role, now()))
    return jsonify(id=account_id), 201


@google_auth.post('/api/accounts/<int:account_id>')
def change_account(account_id):
    require_account_manager()
    active = request.get_json().get('active')
    if not isinstance(active, bool):
        raise Problem('請選擇啟用或停用帳號')
    conn = get_db()
    with transaction(conn):
        account = conn.execute('SELECT * FROM staff_accounts WHERE id=?', (account_id,)).fetchone()
        if not account:
            raise Problem('找不到帳號', status=404)
        if g.account['role'] == 'owner' and account['role'] != 'staff':
            raise Problem('老闆只能管理員工帳號', status=403)
        if account['role'] == 'admin':
            raise Problem('不能停用系統管理員帳號，以免無法管理系統', status=409)
        if bool(account['active']) != active:
            conn.execute('UPDATE staff_accounts SET active=?,version=version+1 WHERE id=?', (int(active), account_id))
            conn.execute('INSERT INTO account_events(account_id,actor,action,created_at) VALUES(?,?,?,?)',
                         (account_id, session['user'], 'enable' if active else 'disable', now()))
    return jsonify(ok=True)
