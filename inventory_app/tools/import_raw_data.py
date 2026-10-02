"""Import reviewed local sources after a complete rehearsal, preserving the account.

python -m tools.import_raw_data --manifest data/normalization/raw-source-manifest.json
Use --apply to write the store database. Raw sources are always read-only.
"""
import argparse
import copy
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

from app.backups import create_backup
from app.common import now, record, transaction
from app.db import connect_db, init_db
from app.exports import invoice_rows
from app.imports import commit_import, preview_import
from tools.import_owner_responses import apply_responses
from tools.reconcile_sources import apply_plan


def normalized_preview(original):
    preview = copy.deepcopy(original)
    identities = defaultdict(list)
    for row in preview['rows']:
        for key in ('code', 'name', 'category', 'supplier', 'unit'):
            row[key] = row[key].strip()
        if row['unit'].lower() == 'kg':
            row['unit'] = 'kg'
        identity = (row['name'], row['unit'])
        if identity not in identities[row['code']]:
            identities[row['code']].append(identity)
    for row in preview['rows']:
        choices = identities[row['code']]
        if len(choices) > 1:
            row['code'] += '-'+str(choices.index((row['name'], row['unit']))+1).zfill(2)
    return preview


def manifest_plan(conn, manifest):
    digest = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    plan = {'id': 'raw-source-'+digest, 'actions': []}
    products = {r['code']: dict(r) for r in conn.execute('SELECT * FROM products')}
    for key, table in [('catalog', 'catalog_cards'), ('invoice', 'invoice_items')]:
        for entry in manifest[key]:
            row = conn.execute(f'SELECT * FROM {table} WHERE source=?', (entry['source'],)).fetchone()
            if row is None or any(row[k] != v for k, v in entry['expected'].items()):
                raise ValueError('來源與核對清單不符：'+entry['source'])
            p = products.get(entry['product_code']) if entry['product_code'] else None
            if entry['product_code'] and not p:
                raise ValueError('清單指定商品不存在：'+entry['product_code'])
            after = {'product_id': p['id'] if p else None}
            if key == 'catalog':
                after.update(pricing_mode='product' if p else 'fixed', independent=0 if p else 1)
            else:
                after.update(fixed=0 if p else 1)
                if p:
                    after['unit'] = p['unit']
            plan['actions'].append({'table': table, 'id': row['id'],
                'before': {k: row[k] for k in set(entry['expected']) | set(after)},
                'after': after, 'reason': entry['reason']+'；來源 '+entry['source']})
    for item in manifest['price_defaults']:
        p = products[item['code']]
        sources = [r[0] for r in conn.execute('SELECT original_price FROM catalog_cards WHERE source=?', (item['source'],))]
        sources += [r[0] for r in conn.execute('SELECT price FROM invoice_items WHERE source=?', (item['source'],))]
        if sources != [item['price']]:
            raise ValueError('補價與原始來源不符')
        plan['actions'].append({'table': 'products', 'id': p['id'], 'before': {'price': None, 'code': p['code']},
            'after': {'price': item['price']}, 'reason': '依已核對來源補空白售價：'+item['source']})
    return plan


def link_verified_photos(conn, media_dir):
    with transaction(conn):
        for product in conn.execute('SELECT * FROM products WHERE image IS NULL').fetchall():
            # Milk case photos may show 24 units while stock is sold in six-unit packs.
            if product['unit'] == '手':
                continue
            card = conn.execute('''SELECT * FROM catalog_cards WHERE product_id=?
                AND image IS NOT NULL ORDER BY id LIMIT 1''', (product['id'],)).fetchone()
            if card is None:
                continue
            if not (media_dir/card['image']).is_file():
                raise ValueError('已對應商品缺少來源圖片')
            conn.execute('UPDATE products SET image=?,version=version+1,updated_at=? WHERE id=?',
                (card['image'], now(), product['id']))
            record(conn, product['id'], None, 'mapping', '接入已核對價目卡照片：'+card['source'],
                None, card['image'], 'raw-data-import')


def verify(conn, preview, reply):
    expected = {r['source']: r for r in preview['rows']}
    actual = conn.execute('''SELECT b.*,p.code,p.name,p.unit FROM batches b
        JOIN products p ON p.id=b.product_id ORDER BY b.id''').fetchall()
    if len(actual) != len(expected):
        raise ValueError('匯入批次数量不符')
    for b in actual:
        r = expected[b['source']]
        if any(b[k] != r[k] for k in ('code', 'name', 'unit', 'quantity', 'cost', 'received_on', 'expires_on')):
            raise ValueError('批次與來源內容不符：'+b['source'])
        if b['saleable'] != int(bool(r['expires_on'])):
            raise ValueError('不得自行改變可售旗標')
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('資料庫完整性檢查失敗')
    rows, issues = invoice_rows(conn)
    if issues:
        raise ValueError('發票對應仍有問題：'+str(issues))
    return {
        'products': conn.execute('SELECT COUNT(*) FROM products').fetchone()[0],
        'batches': len(actual), 'unknown_batches': sum(b['quantity'] is None for b in actual),
        'missing_prices': [dict(r) for r in conn.execute('SELECT code,name FROM products WHERE price IS NULL')],
        'catalog_linked': conn.execute('SELECT COUNT(*) FROM catalog_cards WHERE product_id IS NOT NULL').fetchone()[0],
        'catalog_independent': conn.execute('SELECT COUNT(*) FROM catalog_cards WHERE independent=1').fetchone()[0],
        'invoice_linked': conn.execute('SELECT COUNT(*) FROM invoice_items WHERE product_id IS NOT NULL').fetchone()[0],
        'invoice_fixed': conn.execute('SELECT COUNT(*) FROM invoice_items WHERE fixed=1').fetchone()[0],
        'invoice_rows': len(rows), 'invoice_issues': issues,
        'with_photos': conn.execute('SELECT COUNT(*) FROM products WHERE image IS NOT NULL').fetchone()[0],
        'owner_answers_applied': len(reply['tasks']), 'source_batches_preserved': True,
    }


def run_import(conn, preview, manifest, reply, media_dir):
    commit_import(conn, preview, {'acknowledge_issues': True}, 'raw-data-import')
    apply_plan(conn, manifest_plan(conn, manifest))
    apply_responses(conn, reply)
    link_verified_photos(conn, media_dir)
    return verify(conn, preview, reply)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, default=root.parent/'raw_data')
    parser.add_argument('--data-dir', type=Path, default=root/'data')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    replies = list(args.source_dir.glob('*.json'))
    if len(replies) != 1:
        raise ValueError('請保留一份老闆確認回覆 JSON')
    reply = json.loads(replies[0].read_text('utf-8-sig'))
    manifest = json.loads(args.manifest.read_text('utf-8'))
    original = preview_import(sorted(args.source_dir.glob('*.xlsx')), args.data_dir/'staging')
    if original['fingerprint'] != manifest['fingerprint']:
        raise ValueError('原始 Excel 已變更，需重新核對')
    preview = normalized_preview(original)
    normalized_dir = args.data_dir/'normalization'
    normalized_dir.mkdir(exist_ok=True)
    (normalized_dir/'normalized-preview.json').write_text(json.dumps(preview, ensure_ascii=False), 'utf-8')
    evidence = {'fingerprint': original['fingerprint'], 'manifest': manifest, 'owner': reply}
    key = 'raw-import:'+hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    conn = connect_db(args.data_dir/'inventory.sqlite3')
    try:
        previous = conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        if previous:
            print(json.dumps({'already_applied': True, **json.loads(previous[0])}, ensure_ascii=False))
            return
        if conn.execute('SELECT 1 FROM products').fetchone():
            raise ValueError('此工具只用於空資料庫，不能覆蓋已在使用的庫存')
        rehearsal = connect_db(':memory:')
        try:
            init_db(rehearsal)
            report = run_import(rehearsal, preview, manifest, reply, args.data_dir/'staging/media')
        finally:
            rehearsal.close()
        report.update(created_at=now(), fingerprint=original['fingerprint'],
            owner_reply_sha256=hashlib.sha256(replies[0].read_bytes()).hexdigest())
        (normalized_dir/'import-rehearsal.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        if args.apply:
            backup = create_backup(args.data_dir/'inventory.sqlite3', args.data_dir/'media', args.data_dir.parent/'backups')
            users_before = [tuple(r) for r in conn.execute('SELECT * FROM users')]
            for image in (args.data_dir/'staging/media').iterdir():
                target = args.data_dir/'media'/image.name
                if not target.exists():
                    shutil.copy2(image, target)
            actual = run_import(conn, preview, manifest, reply, args.data_dir/'media')
            if actual != {k:report[k] for k in actual} or users_before != [tuple(r) for r in conn.execute('SELECT * FROM users')]:
                raise ValueError('正式匯入與試跑結果或原帳號不符')
            report['backup_before'] = str(backup)
            report['backup_after'] = str(create_backup(args.data_dir/'inventory.sqlite3', args.data_dir/'media', args.data_dir.parent/'backups'))
            conn.execute('INSERT INTO metadata VALUES(?,?)', (key, json.dumps(report, ensure_ascii=False)))
            (normalized_dir/'raw-import-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps({'applied': args.apply, **report}, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
