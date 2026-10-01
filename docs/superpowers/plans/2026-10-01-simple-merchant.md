# 商家介面簡化 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** 依使用者核定四點，讓店家從商品卡開始並能用表格集中盤點。
**Architecture:** 沿用 Flask API、既有商品詳細面板與模組化 JavaScript。新增 merchant.js 管商品卡與盤點草稿；集中盤點共用既有數量、版本及預留驗證，在單一交易中寫入。
**Tech Stack:** Python 3.12 / Flask / SQLite / 原生 JavaScript。
**Spec:** ../specs/2026-10-01-simple-merchant-design.md

## Global Constraints
- 不寫入正式庫存、不改訂單規則、不覆寫已暫存的首版 Git snapshot。
- 尚未有首個 commit，無法建立 worktree；依使用者要求在現有工作區實作，測試資料隔離。
- 提交作者已由使用者指定；首版與介面簡化更新分別提交。

## Review Focus
- 多批次／未知數量與預留庫存：表格以實體批次為準，空白不等於零。
- 跨頁與篩選：輸入草稿不能消失，所有已填列統一儲存。
- 版本衝突：整批回滾，保留草稿及明確錯誤。
- 重送及連線失敗：同一提交識別碼重試不重複寫入。
- 手機、鍵盤與縮放：所有入口可見，盤點表可局部橫捲，數字輸入有標籤。

### Task 1：集中盤點 API
- [x] 在 tests/test_bulk_counts.py 驗證成功、零、空值、重送、重複批次、版本衝突回滾及預留保護；先確認失敗。
- [x] 將 inventory.count_stock 的交易內動作抽出共用 helper；bulk_count_stock(conn,command,actor_id) 接受 items 陣列及 request_id，最多 200 筆，逐項驗證並原子寫入。
- [x] api.py 新增 POST /api/counts/bulk。成功回傳 results 與 movement_ids；失敗以 fields.batch_id 指出衝突批次。
- [x] 跑新測試及既有盤點／訂單測試。

### Task 2：商品首頁與集中盤點介面
- [x] 建立隔離瀏覽器驗收：登入先看到商品、篩選、點卡操作、展開批次、跨頁草稿、切換卡片草稿、零值儲存、設定與手機版面；確認舊版缺少新介面。
- [x] 新增 static/views/merchant.js，沿用 GET /api/products 的分頁商品／批次資料；集中盤點草稿依 batch_id 保存原版本與輸入。
- [x] 修改 app.js 預設 inventory，改由 merchant.js 畫商品與集中盤點；加入匯出首頁、設定收納與保護草稿。
- [x] 修改 operations.js 將常用操作集中在商品面板，保留既有批次與紀錄。
- [x] 修改 index.html 與新增 merchant.css：三個主要入口、暖色卡片、可存取的表格及手機設定入口。
- [x] 執行隔離瀏覽器驗收並檢查桌機／手機截圖。

### Task 3：驗證與載入
- [x] 跑完整 Python 測試及客人商品瀏覽驗證，檢查 JavaScript 語法。
- [x] 更新 README；完成程式碼自查，確認所有原操作有入口、原始數據與機密未提交。
- [x] 重啟本機服務以載入版本，核对正式資料表雜湊未變。記錄結果。

## Progress
開始：首版 77 檔已暫存，尚未 commit。此輪新修改先保留在 working tree，避免將新版混入使用者要求先推的首版。

驗證：70 項 Python 測試通過；隔離瀏覽器驗證桌機／手機、分類、跨頁／模式／縮放草稿、零值、連線回應遺失後重送、200 列上限、延遲讀取與儲存競爭。程式碼審查提出的兩項 P2 均已修正。正式資料指紋已保存，待載入後核對。

完成：正式服務已重新載入；商品、批次、異動、上下架與訂單資料雜湊完全相同。客人頁 173 商品／10 分類與缺圖排序驗證通過。原先首版仍在 Git 暫存區，本輪修改尚未加入暫存；作者資訊已補齊，依序提交首版與介面簡化更新。
