-- Cloud deployment security for the existing duck_runtime role. Apply after migrations 003-005.
-- New tables remain in private schema duck; no anon/authenticated privileges are granted.
ALTER TABLE duck.line_chats ENABLE ROW LEVEL SECURITY;
CREATE POLICY duck_runtime_access ON duck.line_chats FOR ALL TO duck_runtime USING (true) WITH CHECK (true);
ALTER TABLE duck.line_imports ENABLE ROW LEVEL SECURITY;
CREATE POLICY duck_runtime_access ON duck.line_imports FOR ALL TO duck_runtime USING (true) WITH CHECK (true);
ALTER TABLE duck.line_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY duck_runtime_access ON duck.line_messages FOR ALL TO duck_runtime USING (true) WITH CHECK (true);
ALTER TABLE duck.line_orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY duck_runtime_access ON duck.line_orders FOR ALL TO duck_runtime USING (true) WITH CHECK (true);
ALTER TABLE duck.line_order_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY duck_runtime_access ON duck.line_order_items FOR ALL TO duck_runtime USING (true) WITH CHECK (true);
ALTER TABLE duck.line_order_sales ENABLE ROW LEVEL SECURITY;
CREATE POLICY duck_runtime_access ON duck.line_order_sales FOR ALL TO duck_runtime USING (true) WITH CHECK (true);