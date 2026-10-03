"""Fail-closed configuration for the stateless Cloud Run service."""
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def configure_cloud(app, overrides):
    enabled = overrides.get('CLOUD_MODE', os.environ.get('CLOUD_MODE', '').lower() in {'1', 'true'})
    app.config['CLOUD_MODE'] = enabled
    if not enabled:
        if os.environ.get('K_SERVICE'):
            raise ValueError('Cloud Run requires CLOUD_MODE=true')
        return
    keys = ('DATABASE_URL', 'DATABASE_SCHEMA', 'STORAGE_BACKEND', 'SUPABASE_URL',
            'SUPABASE_SERVICE_KEY', 'SUPABASE_BUCKET', 'SECRET_KEY')
    for key in keys:
        if key not in overrides:
            app.config[key] = os.environ.get(key, '')
    required = keys + ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI', 'GOOGLE_ADMIN_EMAIL')
    for key in required:
        if not isinstance(app.config.get(key), str) or not app.config[key].strip():
            raise ValueError(f'Cloud configuration requires {key}')
    db = urlsplit(app.config['DATABASE_URL'])
    if db.scheme not in {'postgres', 'postgresql'} or not db.hostname or not db.username or not db.password:
        raise ValueError('Cloud DATABASE_URL must be an authenticated PostgreSQL URL')
    if parse_qs(db.query).get('sslmode', [''])[0] not in {'require', 'verify-ca', 'verify-full'}:
        raise ValueError('Cloud PostgreSQL requires TLS (sslmode=require or stronger)')
    schema = app.config['DATABASE_SCHEMA']
    if not re.fullmatch(r'duck(?:_[a-z0-9_]+)?', schema) or len(schema) > 63:
        raise ValueError('DATABASE_SCHEMA must be a private application schema')
    if app.config['STORAGE_BACKEND'] != 'supabase' or app.config['AUTH_MODE'] != 'google':
        raise ValueError('Cloud mode requires Supabase storage and Google login')
    for key in ('SUPABASE_URL', 'GOOGLE_REDIRECT_URI'):
        url = urlsplit(app.config[key])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError(f'{key} requires a clean HTTPS URL')
    if len(app.config['SECRET_KEY']) < 32:
        raise ValueError('Cloud SECRET_KEY requires at least 32 characters')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', app.config['GOOGLE_ADMIN_EMAIL']):
        raise ValueError('GOOGLE_ADMIN_EMAIL requires an email address')
    app.config.update(SESSION_COOKIE_SECURE=True, MAX_CONTENT_LENGTH=12*1024*1024)
    app.config['BACKUP_JOB_RESOURCE'] = overrides.get('BACKUP_JOB_RESOURCE', os.environ.get('BACKUP_JOB_RESOURCE', ''))
    if 'DATA_DIR' not in overrides:
        app.config['DATA_DIR'] = Path(tempfile.gettempdir()) / 'duck-runtime'
