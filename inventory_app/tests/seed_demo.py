"""Create isolated synthetic acceptance data. Never touch the live data directory."""
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.common import now
from app.db import connect_db
from app.inventory import count_stock, receive
from app.products import create_product
from werkzeug.security import generate_password_hash


def main():
    root=Path(__file__).resolve().parents[1]
    target=root/'.qa'/'data'
    app=create_app({'DATA_DIR':target})
    conn=connect_db(app.config['DB_PATH'])
    if conn.execute('SELECT 1 FROM products').fetchone():
        print('QA fixture already exists');conn.close();return
    conn.execute('INSERT INTO users VALUES(1,?)',(generate_password_hash('qa-local-testing-only'),))
    names=['福茂芋頭貢丸450g','小磨坊白胡椒粉','台東初鹿伯爵紅茶牛乳','桂冠魚餃','富里芋香米1.5kg','萬家香零添加醬油',
           '愛之味鮮味脆瓜','鮮乳坊生乳保久乳','桂冠筍香包','Choice牛嫩肩火鍋肉片','中華嫩豆腐','日正高筋麵粉']
    current=date.fromisoformat(now()[:10])
    for i,name in enumerate(names*3):
        p=create_product(conn,{'code':f'DEMO{i+1:03}','name':name+(f' 示範規格{i//12+1}' if i>=12 else ''),
          'unit':'包' if i%3 else '瓶','category':['冷凍食品','調味品','乳飲品'][i%3],
          'supplier':'示範供應商','price':str(45+i*5),'minimum':'5'},1)
        bid=conn.execute('SELECT id FROM batches WHERE product_id=?',(p['id'],)).fetchone()[0]
        if i%6!=0:
            count_stock(conn,{'batch_id':bid,'actual_quantity':'0','expected_version':1,'request_id':str(uuid4())},1)
        if i%6 not in {0,1}:
            expiry=current+timedelta(days= [-5,12,90,120][i%4])
            receive(conn,{'product_id':p['id'],'quantity':str(2 if i%6==2 else 9+i),
              'cost':'35','received_on':current.isoformat(),'expires_on':expiry.isoformat(),'request_id':str(uuid4())},1)
        conn.execute('''INSERT INTO invoice_items(source,category,code,name,price,unit,tax,kind,product_id)
                        VALUES(?,?,?,?,?,?,1,0,?)''',(f'demo-{i}','1734',p['code'],name,p['price'],p['unit'],p['id']))
    conn.close()
    print('QA demo created; synthetic stock only; separate from live data.')


if __name__=='__main__':
    main()
