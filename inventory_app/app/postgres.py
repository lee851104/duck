"""Small, explicit SQLite API adapter for this application's PostgreSQL queries.

Every operation sets search_path transaction-locally, including through a transaction
pooler. No session state or prepared statements are required. Application mutations
share a schema-specific advisory transaction lock, matching BEGIN IMMEDIATE.
"""
import hashlib
import re
import sqlite3
from collections.abc import Mapping


IDENTITY_TABLES = frozenset(('users', 'staff_accounts', 'account_events', 'products',
    'batches', 'movements', 'catalog_cards', 'invoice_items', 'backup_runs',
    'recipes', 'order_events', 'daily_sales', 'daily_sale_lines'))
TABLES = ('users', 'staff_accounts', 'account_events', 'products', 'batches',
    'movements', 'requests', 'imports', 'catalog_cards', 'invoice_items',
    'invoice_exports', 'backup_runs', 'metadata', 'shop_products', 'recipes',
    'recipe_items', 'customer_orders', 'order_items', 'reservations',
    'order_events', 'shop_attempts', 'daily_sales', 'daily_sale_lines', 'daily_sale_movements')
# Tokenize quoted regions first: placeholders inside them are never interpreted.
TOKENS = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*(?:\n|$)|/\*.*?\*/|::|:[A-Za-z_][A-Za-z_0-9]*|\?|;|.", re.S)


def validate_schema(schema):
    if not isinstance(schema, str) or not re.fullmatch(r'duck(?:_[a-z0-9_]+)?', schema) or len(schema) > 63:
        raise ValueError('Use private schema duck or duck_<validated_suffix>')
    return schema


def bind_sql(statement, parameters=()):
    """Translate only bound placeholders, refusing ambiguous/unsupported SQL."""
    if not isinstance(statement, str) or re.search(r'\b(?:PRAGMA|ATTACH|DETACH|INSERT\s+OR)\b', statement, re.I):
        raise sqlite3.ProgrammingError('Unsupported SQL for PostgreSQL')
    if '$' in statement or re.search(r"\bE'", statement, re.I):
        raise sqlite3.ProgrammingError('Dollar and escaped SQL literals are unsupported')
    parts, names, count = [], set(), 0
    tokens = TOKENS.findall(re.sub(r';\s*\Z', '', statement))
    for token in tokens:
        if token == ';':
            raise sqlite3.ProgrammingError('Only one statement is permitted')
        if token == '?':
            count += 1
            parts.append('%s')
        elif token.startswith(':') and token != '::':
            names.add(token[1:])
            parts.append('%(' + token[1:] + ')s')
        else:
            parts.append(token.replace('%', '%%'))
    if names:
        if count or not isinstance(parameters, Mapping) or not names <= parameters.keys():
            raise sqlite3.ProgrammingError('Named SQL parameters do not match')
    elif isinstance(parameters, Mapping) or count != len(parameters):
        raise sqlite3.ProgrammingError('Positional SQL parameters do not match')
    # psycopg only interprets %% when a parameter collection is supplied.
    return ''.join(parts), parameters


class Row:
    def __init__(self, keys, values):
        self._keys, self._values = tuple(keys), tuple(values)

    def keys(self):
        return self._keys

    def __getitem__(self, key):
        return self._values[self._keys.index(key)] if isinstance(key, str) else self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


class Cursor:
    def __init__(self, cursor, identity=False):
        self.rowcount = cursor.rowcount
        self.description = cursor.description
        self.lastrowid = None
        names = tuple(c.name for c in cursor.description) if cursor.description else ()
        self._rows = [Row(names, row) for row in cursor.fetchall()] if names else []
        if identity and self._rows:
            self.lastrowid = self._rows[0][0]
        self._position = 0

    def fetchone(self):
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchall(self):
        rows = self._rows[self._position:]
        self._position = len(self._rows)
        return rows

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class PostgresConnection:
    dialect = 'postgres'

    def __init__(self, dsn, schema='duck'):
        self.schema = validate_schema(schema)
        try:
            import psycopg
        except ImportError:
            raise sqlite3.OperationalError('PostgreSQL requires psycopg[binary]') from None
        self.driver = psycopg
        self.lock_key = int.from_bytes(hashlib.sha256(('inventory:' + schema).encode()).digest()[:8], 'big', signed=True)
        try:
            self.raw = psycopg.connect(dsn, autocommit=True, prepare_threshold=None, connect_timeout=15)
        except psycopg.Error:
            raise sqlite3.OperationalError('PostgreSQL connection failed') from None
        self.in_transaction = False

    def _settings(self, lock=False):
        # Schema is validated; pg_catalog resolves built-ins before application names.
        self.raw.execute(f'SET LOCAL search_path TO pg_catalog, "{self.schema}"')
        if lock:
            self.raw.execute('SELECT pg_advisory_xact_lock(%s)', (self.lock_key,))

    def execute(self, statement, parameters=()):
        try:
            if statement.strip().upper() == 'BEGIN IMMEDIATE':
                if self.in_transaction:
                    raise sqlite3.OperationalError('Nested transactions are unsupported')
                self.raw.execute('BEGIN ISOLATION LEVEL READ COMMITTED')
                self.in_transaction = True
                try:
                    self._settings(lock=True)
                except Exception:
                    self.rollback()
                    raise
                return None
            sql, args = bind_sql(statement, parameters)
            match = re.match(r'\s*INSERT\s+INTO\s+([a-z_]+)\b', statement, re.I)
            identity = bool(match and match[1].lower() in IDENTITY_TABLES and not re.search(r'\bRETURNING\b', sql, re.I))
            if identity:
                sql += ' RETURNING id'
            if self.in_transaction:
                with self.raw.execute(sql, args) as cursor:
                    return Cursor(cursor, identity)
            with self.raw.transaction():
                self._settings(lock=bool(re.match(r'\s*(?:INSERT|UPDATE|DELETE)', statement, re.I)))
                with self.raw.execute(sql, args) as cursor:
                    return Cursor(cursor, identity)
        except self.driver.IntegrityError:
            raise sqlite3.IntegrityError('Database constraint violation') from None
        except self.driver.Error:
            raise sqlite3.OperationalError('PostgreSQL operation failed') from None

    def executemany(self, statement, parameters):
        if self.in_transaction:
            result = None
            for values in parameters:
                result = self.execute(statement, values)
            return result
        self.execute('BEGIN IMMEDIATE')
        try:
            result = self.executemany(statement, parameters)
            self.commit()
            return result
        except Exception:
            self.rollback()
            raise

    def commit(self):
        try:
            self.raw.commit()
        except self.driver.Error:
            raise sqlite3.OperationalError('PostgreSQL commit failed') from None
        finally:
            self.in_transaction = False

    def rollback(self):
        try:
            self.raw.rollback()
        except self.driver.Error:
            raise sqlite3.OperationalError('PostgreSQL rollback failed') from None
        finally:
            self.in_transaction = False

    def close(self):
        self.raw.close()
