"""Build a Windows x64 folder from an explicit, verified data snapshot.

Never copies the checkout wholesale or includes cloud credentials.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED


def build(runtime, packages, seed, destination):
    app_root = Path(__file__).resolve().parents[1]
    if destination.exists():
        raise ValueError('Destination must be new; existing data is never overwritten')
    destination.mkdir(parents=True)
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', '_virtualenv*', '*.pth', 'test', 'tests')
    target = destination/'runtime'; target.mkdir()
    for name in ('python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
        shutil.copy2(runtime/name, target/name)
    shutil.copytree(runtime/'DLLs', target/'DLLs', ignore=ignore)
    shutil.copytree(runtime/'Lib', target/'Lib', ignore=shutil.ignore_patterns(
        '__pycache__','*.pyc','*.pyo','site-packages','test','tests','idlelib','tkinter','ensurepip','turtledemo'))
    shutil.copytree(packages, target/'Lib/site-packages', ignore=ignore)
    (target/'python312._pth').write_text('.\nDLLs\nLib\nLib/site-packages\n../inventory_app\n../portable\n', 'utf-8')
    shutil.copytree(app_root/'app', destination/'inventory_app/app', ignore=ignore)
    shutil.copytree(app_root/'portable', destination/'portable', ignore=ignore)
    shutil.copytree(seed/'data', destination/'data')
    shutil.copytree(seed/'templates', destination/'templates')
    shutil.copy2(seed/'migration-report.json', destination/'migration-report.json')
    shutil.copy2(app_root/'requirements.txt', destination/'套件版本.txt')
    for name, action in [('啟動庫存管理','start'), ('停止庫存管理','stop'), ('還原本機備份','restore')]:
        command = '@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n"%~dp0runtime\\python.exe" -X utf8 -B "%~dp0portable\\launcher.py" '+action+'\r\n'
        command += 'if errorlevel 1 pause\r\n' if action == 'start' else 'pause\r\n'
        (destination/(name+'.cmd')).write_bytes(command.encode('utf-8'))
    report = json.loads((seed/'migration-report.json').read_text('utf-8'))
    text = f'''菜騎鴨庫存管理 — Windows 本機正式搬家版

適用：Windows 10/11，Intel/AMD 64 位元。已內含 Python 3.12 與必要套件，無需安裝 Python。
資料快照時間（台灣）：{report['snapshot_at']}

開始使用
1. 將整個 ZIP 解壓縮到可寫入的本機資料夾（例如 D:\\菜騎鴨）。不要直接在 ZIP 裡啟動。
2. 雙擊「啟動庫存管理.cmd」，瀏覽器會自動開啟。首次自行設定至少 10 個字元的密碼。
3. 先核對商品、庫存及最新營運紀錄，再正式開始記帳。
4. 每日銷售、盤點、商品管理與三份 Excel 同步均在本機執行，不連線雲端庫存。
5. 用完可雙擊「停止庫存管理.cmd」。關閉瀏覽器不會停止背景程式。

正式切換
這是上述時間的雲端資料副本。快照之後的雲端修改不會同步過來。
正式切換後只在一份系統登記庫存，避免本機、雲端各記一半；此包不會停用雲端網站。
各台電腦解壓縮後都是獨立資料，不能自動合併。

資料與 Excel
目前資料保存在 data。原始價目表範本在 templates，請一起保留。
匯出頁會顯示最新三份 Excel 的資料夾位置；等同步完成後再取用。
直接修改 Excel 不會回寫系統。啟動與更新資料後會自動同步，不需要 Microsoft Excel 才能產檔。
這份正式資料包含進價、庫存與營運紀錄，請只交給獲授權使用的人。

備份與還原
運行時每日自動備份；也可用「設定 → 立即備份」。備份在目前資料目錄的 backups。
請將備份複製到另一顆磁碟。只備份到同一台電腦，不能防止硬碟損壞。
「還原本機備份.cmd」接受這個本機版產生的 ZIP（不是三份 Excel ZIP 或雲端 PostgreSQL 備份）。
還原會先停止程式，建立新的 restored-* 資料夾，保留原資料；下次啟動使用還原資料。
還原後使用備份當時的本機密碼。資料夾選擇記錄在 portable-data.json。
完整搬移請先停止程式，再複製整份資料夾（含 templates、data、restored-*）。

注意
請勿放在 Program Files、網路磁碟或正在同步的雲端硬碟資料夾。
不要同時在另一份複本記錄正式庫存。更新程式也不要以舊 data 覆蓋目前 data。
通常網址為 http://127.0.0.1:8765；被占用時會改用 8766～8785，啟動視窗會顯示實際網址。
只能從同一台電腦使用；不開放區域網路。不需要 Google 或 Supabase 帳號。
若啟動失敗，保留錯誤訊息及目前資料目錄 logs/server.log 交給維護者。

授權
Python 授權見 runtime/LICENSE.txt；各套件授權保留在 runtime/Lib/site-packages 的 dist-info 目錄。
'''
    (destination/'使用說明.txt').write_text(text, 'utf-8-sig')
    manifest = {}
    for path in sorted(destination.rglob('*')):
        if path.is_file():
            with path.open('rb') as source:
                manifest[path.relative_to(destination).as_posix()] = hashlib.file_digest(source,'sha256').hexdigest()
    (destination/'files.sha256.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    return len(manifest)


def archive(folder, target):
    with ZipFile(target, 'x', compression=ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                output.write(path, folder.name+'/'+path.relative_to(folder).as_posix())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--seed',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args = parser.parse_args()
    print('Files:',build(args.runtime,args.packages,args.seed,args.destination))
