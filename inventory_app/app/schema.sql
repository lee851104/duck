CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS staff_accounts(
 id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, google_sub TEXT UNIQUE,
 name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'staff' CHECK(role IN ('admin','owner','staff')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, last_login TEXT);
CREATE TABLE IF NOT EXISTS account_events(
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES staff_accounts(id),
 actor TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT '', supplier TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL,
 price TEXT, minimum TEXT, specification TEXT NOT NULL DEFAULT '',
 conversions TEXT NOT NULL DEFAULT '{}', image TEXT, version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batches(
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
 quantity TEXT, cost TEXT, received_on TEXT, expires_on TEXT,
 saleable INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, source TEXT);
CREATE TABLE IF NOT EXISTS movements(
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
 batch_id INTEGER REFERENCES batches(id), kind TEXT NOT NULL, reason TEXT NOT NULL,
 before_value TEXT, after_value TEXT, actor TEXT NOT NULL, created_at TEXT NOT NULL,
 reversal_of INTEGER UNIQUE REFERENCES movements(id));
CREATE TABLE IF NOT EXISTS requests(
 request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports(
 id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
 preview TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS catalog_cards(
 id INTEGER PRIMARY KEY, source TEXT NOT NULL UNIQUE, brand TEXT, name TEXT, specification TEXT,
 original_price TEXT, image TEXT, product_id INTEGER REFERENCES products(id),
 pricing_mode TEXT NOT NULL DEFAULT 'fixed', independent INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS invoice_items(
 id INTEGER PRIMARY KEY, source TEXT UNIQUE NOT NULL, category TEXT, code TEXT, name TEXT,
 price TEXT, unit TEXT, tax INTEGER, kind INTEGER,
 product_id INTEGER REFERENCES products(id), fixed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS invoice_exports(
 id TEXT PRIMARY KEY, revision TEXT NOT NULL, filename TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backup_runs(
 id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, path TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS batches_product ON batches(product_id);
CREATE INDEX IF NOT EXISTS movements_product ON movements(product_id, id);
CREATE TABLE IF NOT EXISTS daily_sales(
 id INTEGER PRIMARY KEY, sold_on TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('posted','void')), created_at TEXT NOT NULL, actor TEXT NOT NULL,
 void_reason TEXT, voided_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS daily_sales_one_posted ON daily_sales(sold_on) WHERE status='posted';
CREATE TABLE IF NOT EXISTS daily_sale_lines(
 id INTEGER PRIMARY KEY, sheet_id INTEGER NOT NULL REFERENCES daily_sales(id),
 product_id INTEGER NOT NULL REFERENCES products(id), name TEXT NOT NULL, code TEXT NOT NULL,
 unit TEXT NOT NULL, quantity TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_sale_movements(
 line_id INTEGER NOT NULL REFERENCES daily_sale_lines(id),
 movement_id INTEGER NOT NULL UNIQUE REFERENCES movements(id));
CREATE TABLE IF NOT EXISTS line_chats(
 chat TEXT PRIMARY KEY, last_on TEXT NOT NULL, last_at TEXT NOT NULL, message_count INTEGER NOT NULL,
 tail TEXT NOT NULL, menu TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS line_imports(
 id INTEGER PRIMARY KEY, chat TEXT NOT NULL, filename TEXT NOT NULL, created_at TEXT NOT NULL, actor TEXT NOT NULL,
 total_messages INTEGER NOT NULL, new_messages INTEGER NOT NULL, customer_messages INTEGER NOT NULL,
 missing_messages INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL CHECK(status IN ('baseline','empty','pending','converting','done','failed')),
 error TEXT, model TEXT, usage TEXT, cost TEXT, started_at TEXT, converted_at TEXT);
CREATE TABLE IF NOT EXISTS line_messages(
 id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES line_imports(id),
 sent_on TEXT NOT NULL, sent_at TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('customer','staff','image','recall','other')), raw TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS line_messages_import ON line_messages(import_id, id);
CREATE TABLE IF NOT EXISTS line_orders(
 id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES line_imports(id),
 sent_on TEXT NOT NULL, sent_at TEXT NOT NULL, customer TEXT NOT NULL, location TEXT NOT NULL,
 action TEXT NOT NULL, carrier TEXT NOT NULL, payment TEXT NOT NULL, note TEXT NOT NULL,
 needs_review INTEGER NOT NULL CHECK(needs_review IN (0,1)), review_reason TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('open','done','dismissed')), source_ids TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 edited_at TEXT);
CREATE INDEX IF NOT EXISTS line_orders_status ON line_orders(status, sent_on, sent_at);
CREATE TABLE IF NOT EXISTS line_order_items(
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES line_orders(id),
 name TEXT NOT NULL, product_id INTEGER REFERENCES products(id), quantity TEXT, unit TEXT NOT NULL,
 unit_price TEXT, processing TEXT NOT NULL, note TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS line_order_items_order ON line_order_items(order_id, id);
-- LINE 訂單帶入哪張每日銷售單；銷售單沖銷後，訂單可以重新帶入。
CREATE TABLE IF NOT EXISTS line_order_sales(
 order_id INTEGER NOT NULL REFERENCES line_orders(id), sheet_id INTEGER NOT NULL REFERENCES daily_sales(id),
 created_at TEXT NOT NULL, PRIMARY KEY(order_id, sheet_id));
CREATE INDEX IF NOT EXISTS line_order_sales_sheet ON line_order_sales(sheet_id);
