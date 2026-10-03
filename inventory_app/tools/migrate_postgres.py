"""Explicit cloud migration; never called by app startup.

python -m tools.migrate_postgres --schema duck --runtime-role duck_runtime
python -m tools.migrate_postgres --schema duck --sqlite PATH_TO_SNAPSHOT

Only MIGRATION_DATABASE_URL is read. Pass credentials through the environment,
never argv. Runtime role provisioning/passwords are managed separately.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from app.common import transaction
from app.db import connect_db
from app.postgres import IDENTITY_TABLES, TABLES, validate_schema


def apply_migrations(conn, runtime_role=None):
    """Migrator credentials only; transactional, serialized, checksum verified."""
    if getattr(conn, 'dialect', '') != 'postgres':
        raise ValueError('Migrations require a PostgreSQL destination')
    schema = validate_schema(conn.schema)
    if runtime_role and (not re.fullmatch(r'duck_[a-z0-9_]+', runtime_role) or len(runtime_role) > 63):
        raise ValueError('Use a dedicated runtime role named duck_<validated_suffix>')
    with conn.raw.transaction():
        conn.raw.execute('SELECT pg_advisory_xact_lock(%s)', (conn.lock_key,))
        conn.raw.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.raw.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC')
        # Supabase roles must not gain access through a pre-existing schema grant.
        for role in ('anon', 'authenticated'):
            if conn.raw.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                conn.raw.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{role}"')
        # Application schema first only during trusted DDL, so CREATE uses it.
        conn.raw.execute(f'SET LOCAL search_path TO "{schema}", pg_catalog')
        conn.raw.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, digest TEXT NOT NULL)')
        for path in sorted((Path(__file__).parents[1] / 'app' / 'sql').glob('*.sql')):
            source = path.read_text('utf-8')
            digest = hashlib.sha256(source.encode()).hexdigest()
            previous = conn.raw.execute('SELECT digest FROM schema_migrations WHERE version=%s', (path.name,)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise ValueError('An applied migration has changed; create a new migration')
                continue
            conn.raw.execute(source, prepare=False)
            conn.raw.execute('INSERT INTO schema_migrations VALUES(%s,%s)', (path.name, digest))
        conn.raw.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM PUBLIC')
        conn.raw.execute(f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA "{schema}" FROM PUBLIC')
        if runtime_role:
            details = conn.raw.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=%s', (runtime_role,)).fetchone()
            if details is None or any(details):
                raise ValueError('Runtime role must exist and must not have administrative attributes')
            if conn.raw.execute('SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s', (runtime_role,)).fetchone():
                raise ValueError('Runtime role must not inherit permissions from other roles')
            owner = conn.raw.execute('SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone()[0]
            if owner == runtime_role:
                raise ValueError('Runtime role must not own the application schema')
            conn.raw.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{runtime_role}"')
            conn.raw.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{runtime_role}"')
            for table in TABLES:
                conn.raw.execute(f'REVOKE ALL ON "{schema}"."{table}" FROM "{runtime_role}"')
                conn.raw.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}"."{table}" TO "{runtime_role}"')
            conn.raw.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{runtime_role}"')
            conn.raw.execute(f'REVOKE ALL ON "{schema}".schema_migrations FROM "{runtime_role}"')
            # Whole-schema pg_dump needs to read migration filenames and checksums.
            conn.raw.execute(f'GRANT SELECT ON "{schema}".schema_migrations TO "{runtime_role}"')


@contextmanager
def sqlite_snapshot(path):
    """Consistent in-memory backup from a read-only source (including its WAL)."""
    path = Path(path).resolve(strict=True)
    source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    snapshot = sqlite3.connect(':memory:')
    try:
        source.backup(snapshot)
        snapshot.execute('PRAGMA query_only=ON')
        if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Source SQLite integrity check failed')
        if snapshot.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Source SQLite foreign key check failed')
        yield snapshot
    finally:
        source.close()
        snapshot.close()


def import_sqlite(source_path, conn):
    """Atomic empty-only import and exact multiset verification, then sequences.

    A source column/schema mismatch is refused instead of silently dropping data.
    The source must already be upgraded by the local application before cutover.
    After exact verification, a missing latest-export metadata marker is seeded
    from SQLite's insertion-order tiebreaker, preserving legacy same-second exports.
    """
    if getattr(conn, 'dialect', '') != 'postgres':
        raise ValueError('Import destination must be PostgreSQL')
    counts = {}
    with sqlite_snapshot(source_path) as source, transaction(conn):
        # Block even writers which do not cooperate with the advisory lock.
        conn.raw.execute('LOCK TABLE ' + ','.join(f'"{conn.schema}"."{table}"' for table in TABLES) + ' IN ACCESS EXCLUSIVE MODE')
        conn.raw.execute('SET CONSTRAINTS ALL DEFERRED')
        for table in TABLES:
            if conn.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
                raise ValueError('Destination must be completely empty; import refused')
        source_tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if source_tables != set(TABLES):
            raise ValueError('Source tables do not match the migration; upgrade the local schema first')
        for table in TABLES:
            columns = [r[1] for r in source.execute(f'PRAGMA table_info("{table}")')]
            dest_columns = [r[0] for r in conn.raw.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position', (conn.schema, table))]
            if columns != dest_columns:
                raise ValueError(f'Source columns do not match destination: {table}')
            rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
            cols = ','.join('"' + column + '"' for column in columns)
            placeholders = ','.join('?' for _ in columns)
            conn.executemany(f'INSERT INTO {table} ({cols}) VALUES({placeholders})', rows)
            actual = [tuple(row) for row in conn.execute(f'SELECT * FROM {table}')]
            if Counter(rows) != Counter(actual):
                raise ValueError(f'Exact content verification failed: {table}')
            counts[table] = len(rows)
        latest = source.execute('SELECT id FROM invoice_exports ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()
        if latest:
            conn.execute("INSERT INTO metadata(key,value) VALUES('latest_invoice_export',?) ON CONFLICT(key) DO NOTHING", (latest[0],))
        for table in sorted(IDENTITY_TABLES):
            name = f'"{conn.schema}"."{table}"'
            conn.raw.execute(f"SELECT setval(pg_get_serial_sequence(%s, 'id'), GREATEST(COALESCE(MAX(id),1),1), MAX(id) IS NOT NULL) FROM {name}", (name,))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', default='duck')
    parser.add_argument('--runtime-role')
    parser.add_argument('--sqlite', type=Path)
    args = parser.parse_args()
    dsn = os.environ.get('MIGRATION_DATABASE_URL')
    if not dsn or not dsn.startswith(('postgresql://', 'postgres://')):
        parser.error('Set MIGRATION_DATABASE_URL to the migrator PostgreSQL DSN')
    conn = None
    try:
        conn = connect_db(dsn, schema=args.schema)
        apply_migrations(conn, args.runtime_role)
        if args.sqlite:
            print(json.dumps({'verified_rows': import_sqlite(args.sqlite, conn)}))
        else:
            print('PostgreSQL schema migration completed')
    except Exception:
        # Driver diagnostics may contain credentials, SQL values or private rows.
        raise SystemExit('Migration did not report success. Verify destination before retrying; nonempty imports are refused.') from None
    finally:
        if conn is not None:
            conn.close()


if __name__ == '__main__':
    main()
