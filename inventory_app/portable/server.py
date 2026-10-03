"""Run a self-contained local instance with authenticated graceful shutdown."""
import json
import os
import secrets
import threading

from launcher import ROOT, STATE, data_dir

# A copied portable app must never inherit cloud credentials or contact production.
for key in list(os.environ):
    if key.startswith(('GOOGLE_', 'SUPABASE_', 'PG')) or key in {
            'CLOUD_MODE', 'K_SERVICE', 'DATABASE_URL', 'DATABASE_SCHEMA', 'SECRET_KEY',
            'STORAGE_BACKEND', 'AUTH_MODE', 'BACKUP_DATABASE_URL', 'BACKUP_JOB_RESOURCE'}:
        os.environ.pop(key, None)

from flask import jsonify, request
from waitress import create_server
from app import create_app
from app.backups import start_backup_worker


def main():
    state = json.loads(STATE.read_text('utf-8'))
    folder = data_dir()
    import msvcrt
    with (folder/'instance.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        app = create_app({'CLOUD_MODE':False, 'AUTH_MODE':'password', 'DATABASE_URL':'',
            'STORAGE_BACKEND':'local', 'DATA_DIR':folder, 'BACKUP_DIR':folder/'backups',
            'SOURCE_DIR':ROOT/'templates', 'CUSTOMER_ORDERING_ENABLED':False})
        shutdown = threading.Event()

        @app.before_request
        def local_host_only():
            if request.host != f"127.0.0.1:{state['port']}":
                return jsonify(error='Local address required'), 403

        @app.get('/__portable/status')
        def status():
            return jsonify(instance=state['instance'])

        @app.post('/__portable/stop')
        def stop():
            if request.headers.get('Origin') or not secrets.compare_digest(
                    request.headers.get('X-Portable-Token',''), state['token']):
                return jsonify(error='Not authorized'), 403
            threading.Timer(0.3, shutdown.set).start()
            return jsonify(stopping=True)

        server = create_server(app, host='127.0.0.1', port=state['port'], threads=4)
        backup_stop = start_backup_worker(app)
        sync_stop = app.extensions['excel_sync'].start()
        thread = threading.Thread(target=server.run, name='http-server', daemon=True)
        thread.start()
        try:
            while thread.is_alive() and not shutdown.wait(1):
                pass
        finally:
            backup_stop.set(); sync_stop.set()
            server.task_dispatcher.shutdown(timeout=30)
            for worker in threading.enumerate():
                if worker.name == 'daily-backup' or worker is app.extensions['excel_sync'].thread:
                    worker.join()
            server.close()
            thread.join(timeout=5)
            if STATE.exists() and json.loads(STATE.read_text('utf-8'))['instance'] == state['instance']:
                STATE.unlink()


if __name__ == '__main__':
    main()
