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
