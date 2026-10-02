"""Fill reviewed missing photos only; never link catalog stock or alter quantities.

python -m tools.import_product_photos --plan data/normalization/photo-plan.json
Add --apply after reviewing the dry-run result. Source workbooks stay read-only.
"""
import argparse
import hashlib
import json
from pathlib import Path

from app.backups import create_backup
from app.common import now, record, transaction
from app.db import connect_db


def apply_photos(conn, plan, media_dir):
    digest = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    key = 'photo-import:' + plan['id']
    with transaction(conn):
        prior = conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        if prior:
            result = json.loads(prior['value'])
            if result['plan_sha256'] != digest:
                raise ValueError('同一識別碼不可使用不同照片計畫')
            return result
        checked, seen = [], set()
        for item in plan['items']:
            table = item['table']
            if table not in {'products', 'catalog_cards'}:
                raise ValueError('照片整理僅支援商品及價目卡')
            identity = 'code' if table == 'products' else 'source'
            row = conn.execute(f'SELECT * FROM {table} WHERE {identity}=?', (item[identity],)).fetchone()
            if not row or row['image'] is not None or any(row[k] != v for k, v in item['expected'].items()):
                raise ValueError('商品已變更或已有照片：' + item[identity])
            if (table, row['id']) in seen:
                raise ValueError('照片計畫含重複商品')
            seen.add((table, row['id']))
            source = conn.execute('SELECT * FROM catalog_cards WHERE source=?', (item['photo_source'],)).fetchone()
            if not source or any(source[k] != v for k, v in item['source_expected'].items()):
                raise ValueError('來源照片或品項已變更')
            filename = source['image']
            if not filename or Path(filename).name != filename or not (Path(media_dir)/filename).is_file():
                raise ValueError('來源照片檔案不存在')
            checked.append((item, row, filename))
        batches = [tuple(r) for r in conn.execute('SELECT * FROM batches ORDER BY id')]
        for item, row, filename in checked:
            if item['table'] == 'products':
                conn.execute('UPDATE products SET image=?,version=version+1,updated_at=? WHERE id=?',
                             (filename, now(), row['id']))
                record(conn, row['id'], None, 'mapping',
                       '補商品照片：' + item['photo_source'] + '；' + item['reason'], None, filename, 'photo-import')
            else:
                conn.execute('UPDATE catalog_cards SET image=? WHERE id=?', (filename, row['id']))
        if batches != [tuple(r) for r in conn.execute('SELECT * FROM batches ORDER BY id')]:
            raise ValueError('照片整理不得修改庫存批次')
        result = {'created_at': now(), 'plan_sha256': digest,
                  'products_filled': sum(i['table'] == 'products' for i, _, _ in checked),
                  'catalog_filled': sum(i['table'] == 'catalog_cards' for i, _, _ in checked),
                  'batches_preserved': True}
        conn.execute('INSERT INTO metadata(key,value) VALUES(?,?)', (key, json.dumps(result, ensure_ascii=False)))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--source-dir', type=Path, default=Path('../raw_data'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text('utf-8'))
    for source in plan['workbooks']:
        name = source['name']
        if Path(name).name != name or hashlib.sha256((args.source_dir/name).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('原始檔已變更，請重新核對照片')
    conn = connect_db(args.data_dir/'inventory.sqlite3')
    rehearsal = connect_db(':memory:')
    try:
        conn.backup(rehearsal)
        result = apply_photos(rehearsal, plan, args.data_dir/'media')
        if args.apply:
            backup = create_backup(args.data_dir/'inventory.sqlite3', args.data_dir/'media', args.data_dir.parent/'backups')
            result = apply_photos(conn, plan, args.data_dir/'media')
            result = {**result, 'backup_before': str(backup)}
            args.plan.with_name('photo-import-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps({'applied': args.apply, **result}, ensure_ascii=False, indent=2))
    finally:
        rehearsal.close()
        conn.close()


if __name__ == '__main__':
    main()
