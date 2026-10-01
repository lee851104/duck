from decimal import Decimal

from .common import Problem, now


def active_reservations(conn, batch_id):
    return conn.execute('''SELECT r.*,o.hold_until,o.pickup_date FROM reservations r
        JOIN customer_orders o ON o.id=r.order_id WHERE r.batch_id=?
        AND o.status IN ('confirmed','ready') AND o.hold_until>=?''', (batch_id,now())).fetchall()


def reserved_quantity(conn, batch_id):
    return sum((Decimal(r['quantity']) for r in active_reservations(conn,batch_id)),Decimal(0))


def protect_reserved(conn, batch_id, quantity, expires_on=None, saleable=None):
    rows=active_reservations(conn,batch_id)
    if not rows:
        return
    if quantity is None or Decimal(quantity)<sum((Decimal(r['quantity']) for r in rows),Decimal(0)):
        raise Problem('這批有客人訂單預留，請先取消或處理訂單後再調整庫存',status=409)
    if saleable is not None and (not saleable or not expires_on or any(expires_on<r['pickup_date'] for r in rows)):
        raise Problem('這批有訂單預留，不能改為不可售或早於取貨日期的效期',status=409)


def expire_orders(conn):
    # Called inside write transactions; reads already ignore expired holds.
    rows=conn.execute("SELECT id FROM customer_orders WHERE status IN ('pending','confirmed','ready') AND hold_until<?",(now(),)).fetchall()
    for row in rows:
        conn.execute("UPDATE customer_orders SET status='expired',updated_at=? WHERE id=?",(now(),row['id']))
        conn.execute('DELETE FROM reservations WHERE order_id=?',(row['id'],))
        conn.execute('INSERT INTO order_events(order_id,status,actor,created_at) VALUES(?,?,?,?)',(row['id'],'expired','system',now()))
