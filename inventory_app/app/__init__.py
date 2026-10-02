import secrets
import sqlite3
import os
import json
from pathlib import Path

from flask import Flask, jsonify, request, session
from werkzeug.exceptions import HTTPException

from .auth import auth, guard
from .common import Problem
from .db import close_db, connect_db, get_db, init_db
from .products import create_product


def create_app(config=None):
    app = Flask(__name__)
    root = Path(__file__).resolve().parent.parent
    app.config.update(DATA_DIR=root/'data', MAX_CONTENT_LENGTH=200*1024*1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    auth_keys = ('AUTH_MODE', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI', 'GOOGLE_ADMIN_EMAIL')
    for key in auth_keys:
        app.config[key] = os.environ.get(key, 'password' if key == 'AUTH_MODE' else '')
    app.config.update(config or {})
    from .cloud_config import configure_cloud
    configure_cloud(app, config or {})
    cloud = app.config['CLOUD_MODE']
    data = Path(app.config['DATA_DIR'])
    data.mkdir(parents=True, exist_ok=True)
    auth_file = data/'auth-config.json'
    if not cloud and auth_file.exists():
        auth_config = json.loads(auth_file.read_text('utf-8'))
        if not isinstance(auth_config, dict) or any(k not in auth_keys or not isinstance(v, str) for k, v in auth_config.items()):
            raise ValueError('auth-config.json must contain only supported string-valued auth settings')
        for key, value in auth_config.items():
            if key not in os.environ and key not in (config or {}):
                app.config[key] = value
    for name in ('media', 'staging', 'exports'):
        (data/name).mkdir(exist_ok=True)
    key_file = data/'secret.key'
    if not app.config.get('SECRET_KEY'):
        if not key_file.exists():
            key_file.write_text(secrets.token_hex(32), encoding='ascii')
        app.config['SECRET_KEY'] = key_file.read_text('ascii')
    app.config['DATA_DIR'] = data
    app.config['DB_PATH'] = data/'inventory.sqlite3'
    app.config.setdefault('SOURCE_DIR', root.parent/'原始資料')
    app.config.setdefault('BACKUP_DIR', root/'backups')
    if not cloud:
        conn = connect_db(app.config['DB_PATH'])
        try:
            init_db(conn)
            from .shop_catalog import initialize_shop
            initialize_shop(conn)
        finally:
            conn.close()
    app.teardown_appcontext(close_db)
    app.before_request(guard)
    app.register_blueprint(auth)
    from .google_auth import google_auth, init_google
    init_google(app)
    app.register_blueprint(google_auth)
    from .api import api
    app.register_blueprint(api)
    from .shop_api import shop
    app.register_blueprint(shop)

    @app.get('/health')
    def health():
        try:
            # Verify the migrated schema too, without creating or modifying it.
            get_db().execute('SELECT COUNT(*) FROM metadata').fetchone()
        except sqlite3.Error:
            return jsonify(status='unavailable'), 503
        return jsonify(status='ok')

    @app.errorhandler(Problem)
    def problem(error):
        return jsonify(error={'code': error.code, 'message': error.message, 'fields': error.fields}), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error={'code': 'http', 'message': '找不到頁面或請求格式不正確', 'fields': {}}), error.code

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.exception('Database failure')
        return jsonify(error={'code': 'database', 'message': '資料暫時無法儲存，請稍後重試', 'fields': {}}), 503

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        if request.path.startswith(('/api/', '/auth/')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/api/products')
    def add_product():
        return jsonify(create_product(get_db(), request.get_json(), session['user']))

    return app
