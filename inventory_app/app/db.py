import sqlite3
from pathlib import Path

from flask import current_app, g


def connect_db(path, schema='duck'):
    if str(path).startswith(('postgresql://', 'postgres://')):
        from .postgres import PostgresConnection
        return PostgresConnection(str(path), schema)
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db(conn):
    if getattr(conn, 'dialect', '') == 'postgres':
        raise RuntimeError('Run explicit PostgreSQL migrations before starting the app')
    conn.executescript(Path(__file__).with_name('schema.sql').read_text('utf-8'))
    columns = {row[1] for row in conn.execute('PRAGMA table_info(catalog_cards)')}
    if 'independent' not in columns:
        conn.execute('ALTER TABLE catalog_cards ADD COLUMN independent INTEGER NOT NULL DEFAULT 0')
    # 舊資料庫補上「老闆手動修改 LINE 訂單」的時間欄位。
    if 'edited_at' not in {row[1] for row in conn.execute('PRAGMA table_info(line_orders)')}:
        conn.execute('ALTER TABLE line_orders ADD COLUMN edited_at TEXT')
    conn.executescript(Path(__file__).with_name('shop_schema.sql').read_text('utf-8'))


def get_db():
    if 'db' not in g:
        g.db = connect_db(current_app.config.get('DATABASE_URL') or current_app.config['DB_PATH'],
                          schema=current_app.config.get('DATABASE_SCHEMA', 'duck'))
    return g.db


def close_db(error=None):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()
