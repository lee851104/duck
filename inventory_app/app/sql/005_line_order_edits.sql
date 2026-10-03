-- 老闆手動修改 LINE 訂單的時間；沒改過是 NULL。
ALTER TABLE line_orders ADD COLUMN IF NOT EXISTS edited_at TEXT;
