import secrets
import sqlite3
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
    app.config.update(config or {})
    data = Path(app.config['DATA_DIR'])
    data.mkdir(parents=True, exist_ok=True)
    for name in ('media', 'staging', 'exports'):
        (data/name).mkdir(exist_ok=True)
    key_file = data/'secret.key'
    if not app.config.get('SECRET_KEY'):
        if not key_file.exists():
            key_file.write_text(secrets.token_hex(32), encoding='ascii')
        app.config['SECRET_KEY'] = key_file.read_text('ascii')
    app.config['DATA_DIR'] = data
    app.config['DB_PATH'] = data/'inventory.sqlite3'
    app.config.setdefault('SOURCE_DIR', root.parent/('raw_data' if (root.parent/'raw_data').is_dir() else '原始資料'))
    app.config.setdefault('BACKUP_DIR', root/'backups')
    conn = connect_db(app.config['DB_PATH'])
    init_db(conn)
    from .shop_catalog import initialize_shop
    initialize_shop(conn)
    conn.close()
    app.teardown_appcontext(close_db)
    app.before_request(guard)
    app.register_blueprint(auth)
    from .api import api
    app.register_blueprint(api)
    from .shop_api import shop
    app.register_blueprint(shop)
    from .excel_sync import ExcelSync
    app.extensions['excel_sync'] = ExcelSync(app)

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
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        # Only committed writes schedule a snapshot; errors and preview requests
        # must not publish partial or hypothetical inventory changes.
        if (request.method in {'POST', 'PATCH', 'PUT', 'DELETE'} and response.status_code < 300
                and request.path.startswith('/api/')
                and request.path not in {'/api/login', '/api/logout', '/api/setup',
                    '/api/daily-sales/preview', '/api/excel-sync', '/api/invoice-exports'}
                and not request.path.startswith('/api/imports/preview')):
            app.extensions['excel_sync'].request()
        return response

    @app.post('/api/products')
    def add_product():
        return jsonify(create_product(get_db(), request.get_json(), session['user']))

    return app
