"""Apply a reviewed local source plan, with backup, optimistic checks and history.

Run from inventory_app: python -m tools.reconcile_sources --plan <local JSON>
Business-data plans and reports belong under data/normalization (Git ignored).
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.common import decimal_text, now, number, record, transaction
from app.db import connect_db, init_db


ALLOWED = {
    'products': {'price', 'specification'},
    'catalog_cards': {'product_id', 'pricing_mode', 'independent'},
    'invoice_items': {'product_id', 'fixed', 'unit'},
}


def apply_plan(conn, plan):
    key = 'reconciliation:' + plan['id']
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with transaction(conn):
        prior = conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        if prior:
            report = json.loads(prior['value'])
            if report['plan_sha256'] != digest:
                raise ValueError('同一整理識別碼不能套用不同計畫')
            return report
        for guard in plan.get('guards', []):
            if guard['table'] not in ALLOWED:
                raise ValueError('不支援的來源資料表')
            row = conn.execute(f'SELECT * FROM {guard["table"]} WHERE id=?', (guard['id'],)).fetchone()
            if not row or any(row[k] != v for k, v in guard['before'].items()):
                raise ValueError(f'來源已變更：{guard["table"]} #{guard["id"]}')
        checked = []
        seen = set()
        for action in plan['actions']:
            table, row_id, after = action['table'], action['id'], action['after']
            if table not in ALLOWED or not after or not set(after) <= ALLOWED[table]:
                raise ValueError('不支援的資料欄位')
            if (table, row_id) in seen:
                raise ValueError('同一筆資料只能有一個整理動作')
            seen.add((table, row_id))
            row = conn.execute(f'SELECT * FROM {table} WHERE id=?', (row_id,)).fetchone()
            if not row or any(row[k] != v for k, v in action['before'].items()):
                raise ValueError(f'資料已變更：{table} #{row_id}，請重新比對')
            if table == 'products' and 'price' in after:
                if row['price'] is not None:
                    raise ValueError('來源補價只能填寫原本空白的售價')
                if decimal_text(number(after['price'], '來源售價')) != after['price']:
                    raise ValueError('來源售價格式不正確')
            if after.get('product_id'):
                p = conn.execute('SELECT * FROM products WHERE id=?', (after['product_id'],)).fetchone()
                if not p:
                    raise ValueError('對應的庫存商品不存在')
                if table == 'invoice_items' and after.get('unit', row['unit']) != p['unit']:
                    raise ValueError('發票單位必須採用已核對的庫存單位')
            checked.append((action, dict(row)))
        batches_before = [dict(r) for r in conn.execute('SELECT * FROM batches ORDER BY id')]
        changes = []
        for action, old in checked:
            table, row_id = action['table'], action['id']
            after = dict(action['after'])
            if table == 'products':
                after.update(version=old['version']+1, updated_at=now())
            columns = ','.join(f'{field}=?' for field in after)
            conn.execute(f'UPDATE {table} SET {columns} WHERE id=?', (*after.values(), row_id))
            pid = row_id if table == 'products' else after.get('product_id', old.get('product_id'))
            if pid:
                price_change = table == 'products' and 'price' in after
                record(conn, pid, None, 'price' if price_change else 'mapping', action['reason'],
                       old['price'] if price_change else json.dumps(old, ensure_ascii=False),
                       after['price'] if price_change else json.dumps(after, ensure_ascii=False),
                       'source-reconciliation')
            changes.append({'table':table, 'id':row_id, 'before':old, 'after':after,
                            'reason':action['reason']})
        if batches_before != [dict(r) for r in conn.execute('SELECT * FROM batches ORDER BY id')]:
            raise ValueError('資料整理不應修改任何庫存批次')
        if conn.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('商品關聯檢查失敗')
        report = {'id':plan['id'], 'plan_sha256':digest, 'created_at':now(),
                  'changes':changes, 'pending_questions':plan.get('pending_questions', []),
                  'stock_unchanged':True}
        conn.execute('INSERT INTO metadata(key,value) VALUES(?,?)',
                     (key, json.dumps(report, ensure_ascii=False)))
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1]/'data')
    parser.add_argument('--backup-dir', type=Path, default=Path(__file__).resolve().parents[1]/'backups')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text('utf-8'))
    conn = connect_db(args.data_dir/'inventory.sqlite3')
    try:
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = args.backup_dir/('before_reconciliation_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
        with sqlite3.connect(backup) as destination:
            conn.backup(destination)
        init_db(conn)
        report = apply_plan(conn, plan)
        report['backup'] = str(backup)
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('資料庫完整性檢查失敗')
        output = args.plan.with_name(args.plan.stem+'-result.json')
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'changes':len(report['changes']), 'backup':str(backup),
                          'report':str(output), 'stock_unchanged':report['stock_unchanged']}, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
