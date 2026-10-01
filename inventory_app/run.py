import argparse
from pathlib import Path

from waitress import serve

from app import create_app
from app.backups import restore_backup, start_backup_worker


def main():
    parser=argparse.ArgumentParser(description='菜騎鴨庫存管理')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--restore', type=Path)
    parser.add_argument('--destination', type=Path)
    args=parser.parse_args()
    if args.restore:
        if not args.destination:
            parser.error('--restore 必須提供空的 --destination')
        restore_backup(args.restore,args.destination)
        print('還原完成。確認內容後再使用 --data-dir 指定該資料夾啟動。')
        return
    config={'DEMO':args.demo}
    if args.data_dir:
        config['DATA_DIR']=args.data_dir.resolve()
        config['BACKUP_DIR']=args.data_dir.resolve()/'backups'
    app=create_app(config)
    stop=start_backup_worker(app)
    print(f'菜騎鴨庫存管理：http://127.0.0.1:{args.port}',flush=True)
    try:
        serve(app,host='127.0.0.1',port=args.port,threads=4)
    finally:
        stop.set()


if __name__=='__main__':
    main()
