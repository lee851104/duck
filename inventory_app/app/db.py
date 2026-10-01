import sqlite3
from pathlib import Path

from flask import current_app, g


def connect_db(path):
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db(conn):
    conn.executescript(Path(__file__).with_name('schema.sql').read_text('utf-8'))
    conn.executescript(Path(__file__).with_name('shop_schema.sql').read_text('utf-8'))


def get_db():
    if 'db' not in g:
        g.db = connect_db(current_app.config['DB_PATH'])
    return g.db


def close_db(error=None):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()
