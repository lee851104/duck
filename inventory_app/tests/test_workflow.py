import tempfile
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.backups import create_backup, restore_backup
from app.common import Problem
from app.db import connect_db, init_db
from app.dashboard import list_products
from app.exports import build_invoice_xlsx
from app.inventory import receive, issue, count_stock
from app.products import create_product, update_product


class WorkflowTest(unittest.TestCase):
    def test_inventory_price_export_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            conn=connect_db(root/'inventory.sqlite3')
            init_db(conn)
            p=create_product(conn,{'code':'0001','name':'貢丸','unit':'包','price':'150'},1)
            opening=conn.execute('SELECT * FROM batches').fetchone()
            count_stock(conn,{'batch_id':opening['id'],'expected_version':1,'actual_quantity':'0','request_id':str(uuid4())},1)
            batches=[]
            for quantity,expiry in [('2','2027-01-18'),('7','2027-02-24')]:
                batches.append(receive(conn,{'product_id':p['id'],'quantity':quantity,'cost':'125',
                    'received_on':'2026-10-01','expires_on':expiry,'request_id':str(uuid4())},1))
            allocations=[{'batch_id':batches[0]['batch_id'],'quantity':'2','expected_version':1},
                         {'batch_id':batches[1]['batch_id'],'quantity':'1','expected_version':1}]
            issue(conn,{'product_id':p['id'],'allocations':allocations,'reason':'銷售','request_id':str(uuid4())},1,date(2026,10,1))
            count_stock(conn,{'batch_id':batches[1]['batch_id'],'actual_quantity':'5','expected_version':2,'request_id':str(uuid4())},1)
            update_product(conn,p['id'],{'price':'160'},1,1)
            conn.execute("INSERT INTO invoice_items(source,category,code,name,price,unit,tax,kind,product_id) VALUES('test','1734','0001','貢丸','150','包',1,0,?)",(p['id'],))
            result=build_invoice_xlsx(conn,root/'exports')
            self.assertEqual(result['row_count'],1)
            backup=create_backup(root/'inventory.sqlite3',root/'media',root/'backups')
            conn.close()
            restore_backup(backup,root/'restored')
            restored=connect_db(root/'restored'/'inventory.sqlite3')
            try:
                row=list_products(restored,'','',1,10,date(2026,10,1))['items'][0]
                self.assertEqual(row['quantity'],'5')
                self.assertEqual(row['price'],'160')
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM movements').fetchone()[0],8)
            finally:
                restored.close()

    def test_two_connections_cannot_apply_stale_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'db'
            one=connect_db(path);two=connect_db(path)
            try:
                init_db(one)
                p=create_product(one,{'code':'T','name':'測試','unit':'包'},1)
                b=receive(one,{'product_id':p['id'],'quantity':'2','cost':'1',
                    'received_on':'2026-10-01','expires_on':'2027-01-01','request_id':str(uuid4())},1)
                command={'product_id':p['id'],'reason':'銷售','request_id':str(uuid4()),
                    'allocations':[{'batch_id':b['batch_id'],'quantity':'2','expected_version':1}]}
                issue(one,command,1,date(2026,10,1))
                with self.assertRaises(Problem):
                    issue(two,{**command,'request_id':str(uuid4())},1,date(2026,10,1))
                self.assertEqual(two.execute('SELECT quantity FROM batches WHERE id=?',(b['batch_id'],)).fetchone()[0],'0')
            finally:
                one.close();two.close()
