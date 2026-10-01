CREATE TABLE IF NOT EXISTS shop_products(
 product_id INTEGER PRIMARY KEY REFERENCES products(id), published INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS recipes(
 id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 icon TEXT NOT NULL DEFAULT '🍽️', theme TEXT NOT NULL DEFAULT 'noodles', tag TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', steps TEXT NOT NULL DEFAULT '', published INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1, image TEXT);
CREATE TABLE IF NOT EXISTS recipe_items(
 recipe_id INTEGER NOT NULL REFERENCES recipes(id), product_id INTEGER NOT NULL REFERENCES products(id),
 quantity INTEGER NOT NULL CHECK(quantity>0 AND quantity<=99), optional INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(recipe_id,product_id));
CREATE TABLE IF NOT EXISTS customer_orders(
 id TEXT PRIMARY KEY, number TEXT NOT NULL UNIQUE, token_hash TEXT NOT NULL UNIQUE,
 client_hash TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL,
 status TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, pickup_date TEXT NOT NULL,
 pickup_slot TEXT NOT NULL, hold_until TEXT NOT NULL, total TEXT NOT NULL, snapshot TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(
 order_id TEXT NOT NULL REFERENCES customer_orders(id), product_id INTEGER NOT NULL REFERENCES products(id),
 name TEXT NOT NULL, unit TEXT NOT NULL, quantity TEXT NOT NULL, price TEXT NOT NULL,
 PRIMARY KEY(order_id,product_id));
CREATE TABLE IF NOT EXISTS reservations(
 order_id TEXT NOT NULL REFERENCES customer_orders(id), batch_id INTEGER NOT NULL REFERENCES batches(id),
 quantity TEXT NOT NULL, PRIMARY KEY(order_id,batch_id));
CREATE TABLE IF NOT EXISTS order_events(
 id INTEGER PRIMARY KEY, order_id TEXT NOT NULL REFERENCES customer_orders(id),
 status TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shop_attempts(client_hash TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS order_status_index ON customer_orders(status,created_at);
CREATE INDEX IF NOT EXISTS reservation_batch_index ON reservations(batch_id);
CREATE INDEX IF NOT EXISTS attempts_index ON shop_attempts(client_hash,created_at);
