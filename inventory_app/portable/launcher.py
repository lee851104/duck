"""Relocatable, loopback-only launcher; never needs a system Python installation."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'portable-state.json'
DATA_CHOICE = ROOT / 'portable-data.json'
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def data_dir():
    value = json.loads(DATA_CHOICE.read_text('utf-8'))['folder'] if DATA_CHOICE.exists() else 'data'
    folder = (ROOT / value).resolve()
    if not folder.is_relative_to(ROOT) or folder == ROOT:
        raise ValueError('資料路徑必須在這份可攜版資料夾內。')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def read_state():
    try:
        return json.loads(STATE.read_text('utf-8'))
    except (OSError, ValueError):
        return None


def request(state, path, stop=False):
    url = f"http://127.0.0.1:{int(state['port'])}"
    req = urllib.request.Request(url + path, data=b'' if stop else None,
        headers={'X-Portable-Token': state['token']} if stop else {})
    with HTTP.open(req, timeout=3) as response:
        return json.load(response)


def running(state):
    try:
        return bool(state and request(state, '/__portable/status')['instance'] == state['instance'])
    except (OSError, ValueError, KeyError):
        return False


@contextlib.contextmanager
def launcher_lock():
    import msvcrt
    with (ROOT / 'launcher.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('正在啟動或停止，請等候該視窗完成。') from None
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def start(open_browser=True):
    state = read_state()
    if not running(state):
        folder = data_dir()
        logs = folder / 'logs'; logs.mkdir(exist_ok=True)
        state = {'instance': secrets.token_hex(16), 'token': secrets.token_urlsafe(32)}
        for port in range(8765, 8786):
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', port))
                except OSError:
                    continue
                state['port'] = port
                break
        else:
            raise RuntimeError('8765～8785 連接埠皆被使用，請先關閉其他庫存程式。')
        STATE.write_text(json.dumps(state), 'utf-8')
        with (logs / 'server.log').open('ab') as log:
            process = subprocess.Popen([str(ROOT/'runtime/python.exe'), '-X', 'utf8', '-B',
                str(ROOT/'portable/server.py')], cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(90):
            if running(state):
                break
            if process.poll() is not None:
                raise RuntimeError('啟動失敗，請查看 data/logs/server.log。')
            time.sleep(0.5)
        else:
            raise RuntimeError('啟動仍未完成，請查看 data/logs/server.log，稍後重試。')
    url = f"http://127.0.0.1:{state['port']}"
    print('庫存系統已啟動：' + url)
    if open_browser:
        webbrowser.open(url)
    return state


def stop():
    state = read_state()
    if not running(state):
        print('這份庫存系統目前未執行。')
        return
    request(state, '/__portable/stop', stop=True)
    for _ in range(240):
        if not STATE.exists():
            print('已安全停止，可以備份或搬移整個資料夾。')
            return
        time.sleep(0.5)
    raise RuntimeError('仍在完成備份或 Excel 同步，請稍後再試；不要搬移資料夾。')


def restore(archive):
    stop()
    from app.backups import restore_backup
    destination = ROOT / ('restored-' + time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
    restore_backup(Path(archive).resolve(), destination)
    tmp = DATA_CHOICE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'folder': destination.name}), 'utf-8')
    os.replace(tmp, DATA_CHOICE)
    print('還原完成，下次啟動使用：' + str(destination))
    print('原資料保留；請用備份當時的本機管理密碼登入。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'restore'])
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--archive')
    args = parser.parse_args()
    try:
        with launcher_lock():
            if args.action == 'start':
                start(not args.no_browser)
            elif args.action == 'stop':
                stop()
            else:
                archive = args.archive or input('請貼上本機備份 ZIP 的完整路徑：').strip().strip('"')
                restore(archive)
    except Exception as exc:
        print('未完成：' + str(exc))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
