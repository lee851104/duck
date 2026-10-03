-- LINE 訂單帶入哪張每日銷售單；銷售單沖銷後，訂單可以重新帶入。
CREATE TABLE IF NOT EXISTS line_order_sales(
 order_id BIGINT NOT NULL REFERENCES line_orders(id) DEFERRABLE INITIALLY IMMEDIATE,
 sheet_id BIGINT NOT NULL REFERENCES daily_sales(id) DEFERRABLE INITIALLY IMMEDIATE,
 created_at TEXT NOT NULL, PRIMARY KEY(order_id, sheet_id));
CREATE INDEX IF NOT EXISTS line_order_sales_sheet ON line_order_sales(sheet_id);
