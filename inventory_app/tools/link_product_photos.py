"""Apply the reviewed original-photo manifest without changing SKU/pricing mappings."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.common import now, record, transaction
from app.db import connect_db


def main():
    root = Path(__file__).resolve().parent.parent
    data = root / 'data'
    manifest = json.loads((data / 'normalization/photo-links.json').read_text('utf-8'))
    conn = connect_db(data / 'inventory.sqlite3')
    backup = root / 'backups' / ('before_photos_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3')
    with sqlite3.connect(backup) as destination:
        conn.backup(destination)
    changed = []
    with transaction(conn):
        for item in manifest['links']:
            product = conn.execute('SELECT * FROM products WHERE code=?', (item['code'],)).fetchone()
            card = conn.execute('SELECT * FROM catalog_cards WHERE id=?', (item['card_id'],)).fetchone()
            assert product and product['name'] == item['product_name']
            assert card and card['source'] == item['source'] and card['name'] == item['card_name']
            assert (data / 'media' / item['image']).is_file()
            if product['image'] == item['image']:
                continue
            assert product['image'] is None, 'Do not overwrite another photo decision'
            conn.execute('UPDATE products SET image=?,version=version+1,updated_at=? WHERE id=?',
                         (item['image'], now(), product['id']))
            record(conn, product['id'], None, 'mapping', '接入原始價目表商品照片：' + item['source'],
                   None, item['image'], 'photo-import')
            changed.append(item['code'])
        for item in manifest['card_image_corrections']:
            row = conn.execute('SELECT * FROM catalog_cards WHERE id=?', (item['card_id'],)).fetchone()
            assert row['source'] == item['source'] and (data/'media'/item['image']).is_file()
            conn.execute('UPDATE catalog_cards SET image=? WHERE id=?', (item['image'], item['card_id']))
        for item in manifest['product_image_corrections']:
            row = conn.execute('SELECT * FROM products WHERE code=?', (item['code'],)).fetchone()
            assert row['name'] == item['name']
            if row['image'] != item['image']:
                conn.execute('UPDATE products SET image=?,version=version+1,updated_at=? WHERE id=?',
                             (item['image'], now(), row['id']))
                record(conn, row['id'], None, 'mapping', '修正 Excel 重疊舊照片', row['image'], item['image'], 'photo-import')
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    report = {'backup': str(backup), 'new_links': changed, 'with_photos': conn.execute(
        'SELECT COUNT(*) FROM products WHERE image IS NOT NULL').fetchone()[0], 'missing': [dict(r) for r in conn.execute(
        'SELECT code,name FROM products WHERE image IS NULL ORDER BY code')]}
    (data/'normalization/photo-link-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    conn.close()
    print(json.dumps({'new_links': len(changed), 'with_photos': report['with_photos'], 'missing': len(report['missing']), 'backup': str(backup)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
