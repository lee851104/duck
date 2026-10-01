# 客人選購與三道料理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在既有 Flask 系統提供客人分類選購、三道料理購物車及店家確認／取貨流程。
**Architecture:** 同一 SQLite 商品來源，新增獨立客人 API／頁面和持久化訂單／預留。店家確認才預留，取貨才扣庫存；原本庫存操作亦檢查預留。雲端 PostgreSQL 遷移另屬已記錄的部署工作。
**Tech Stack:** 現有 Flask、SQLite、原生 JS/CSS、unittest、Playwright。無新依賴。
**Spec:** D:/duck/docs/superpowers/specs/2026-10-01-customer-shopping-design.md

## Global Constraints

使用者已明確授權實作；自行在本對話依序完成，不重複要求開始確認。無 Git，不創建 worktree。原始資料唯讀，真實未知庫存不改。固定整包商品，各品原價加總；調味料可取消，示意圖不冒充產品實拍。客人不能讀取成本、供應商、批次或後台資訊。送單待確認，到店取貨付款。

## Review Focus

- 同 SKU 跨料理加總與客戶竄改價格：伺服器重新展開商品並計價、比較 quote。
- 同時確認／店內銷售競爭：交易、批次預留、版本與同次操作冪等測試。
- 確認後過期或被盤點：禁止交付及破壞預留，取消可釋放。
- 私人訂單查詢：高熵 token hash、不得流水號直接查、送單持久限流。
- 可用量未知／照片缺漏／手機長品名：真實資料演練與隔離瀏覽器驗收。

### Task 1: 商品公開投影與三道料理
Files: app/shop_schema.sql, app/shop_catalog.py, app/shop_api.py, app/auth.py, app/__init__.py; tests/test_shop.py.
Interfaces: initialize_shop(conn); public_products(conn, date); recipe_catalog(conn, date); quote(conn, selections, date).
- [x] 先寫商品隱私、原價計算、取消調味料、未知庫存及同商品彙整測試並確認失敗。
- [x] 建立上架設定及料理關係，三道素材按 code 對應，不更動實際數量。
- [x] 實作唯讀公開 API、精確 CSRF/權限邊界；跑測試。

### Task 2: 訂單、預留及既有庫存整合
Files: app/shop_orders.py, app/reservations.py; modify app/inventory.py, app/dashboard.py; tests/test_shop.py.
Interfaces: create_order(conn, body, client_identity, date); transition_order(conn, id, action, actor, request_id, date); reserved_quantity(conn, bid).
- [x] 先寫送單重試、價格更新、確認搶庫存、取貨扣一次、取消、預留下的盤點／出貨／沖銷測試並確認失敗。
- [x] 訂單與事件、私人查詢、逾時釋放、原庫存操作護欄在同交易完成。
- [x] 全套 unittest；核對原庫存行為未退化。

### Task 3: 客人與店家介面
Files: app/templates/shop.html, shop_admin.html; app/static/shop.css, shop.js, shop_admin.js; app/static/dishes/*.svg; admin entry links.
- [x] 客人手機優先三入口，料理詳情、調味料取消、購物車、送單、私密查詢；保留搜尋／返回位置。
- [x] 店家訂單分頁／備貨／確認取貨取消；料理編輯與商品上下架；營業取貨時段设置。
- [x] 增加 isolated browser test：三道菜、價格重算、選購、送單到取貨、手機無橫向溢出與缺圖。

### Task 4: 驗證與交付
- [x] 真實資料庫先備份再套用新增表與種子；不產生正式測試訂單。
- [x] 執行所有 unit/API 測試、桌機手機瀏覽器測試；邀請一次最終只讀 code review 並修正重要問題。
- [x] 記錄已完成和限制；重啟本機服務並提供 /shop 入口。
