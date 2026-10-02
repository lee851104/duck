"""Run with python -m tests.serve_daily_sales; uses only disposable synthetic data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from app import create_app
from app.db import connect_db
from app.products import create_product
from werkzeug.security import generate_password_hash
from waitress import serve

def main():
    with TemporaryDirectory(prefix='duck-sales-qa-') as folder:
        app=create_app({'DATA_DIR':Path(folder),'SECRET_KEY':'qa-only','TODAY':'2026-10-02','DEMO':True})
        conn=connect_db(app.config['DB_PATH'])
        conn.execute('INSERT INTO users VALUES(1,?)',(generate_password_hash('daily-sales-qa-only'),))
        for code,name,unit in [('A','番茄牛肉湯','包'),('B','去骨雞腿排','公斤'),('C','烏龍麵','包'),('D','玉米粒','罐')]:
            p=create_product(conn,{'code':code,'name':name,'unit':unit,'category':'冷凍食材' if code!='D' else '常溫食品'},1)
            conn.execute("UPDATE batches SET quantity='3',saleable=1,expires_on='2026-10-05' WHERE product_id=?",(p['id'],))
            conn.execute("INSERT INTO batches(product_id,quantity,saleable,expires_on) VALUES(?,'7',1,'2027-01-01')",(p['id'],))
        conn.close()
        print('QA server http://127.0.0.1:8770',flush=True)
        serve(app,host='127.0.0.1',port=8770)


if __name__ == '__main__':
    main()
