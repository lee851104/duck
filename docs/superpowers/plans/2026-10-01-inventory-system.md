# 菜騎鴨一頁式庫存系統 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立老闆可用的簡約庫存系統，以單一固定畫面切換總覽、庫存、價目表與紀錄。

**Architecture:** Python 應用程式提供 JSON API，SQLite 保存商品、批次與異動，圖片另存。原生 HTML/CSS/JavaScript 負責固定高度的單頁介面，不引入前端框架。第一版在本機登入操作，資料與介面保留未來部署的邊界。

**Tech Stack:** Python 3.12、Flask 3.1 系列、Waitress、SQLite（標準庫）、openpyxl 3.1.5（僅讀取）、Pillow、unittest；發票 XLSX 匯出使用 ZIP/XML 標準庫產生七欄純值文件。

**Spec:** `docs/superpowers/specs/2026-10-01-inventory-design.md`

## Global Constraints

- 「採繁體中文、白底、深色文字與綠色主要按鈕。」
- 「空白庫存代表未知，零代表已確認沒有庫存；兩者分開。」
- 「每次確認提交須一次完成庫存與紀錄儲存，防止重複點擊造成重複入帳。」
- 「原始圖片另存，備份包含資料庫及圖片；每日自動備份，上線前驗證還原。」
- 「設計驗收以電腦 1366×768、手機 390×844 為基準：正常字級下主要畫面無整頁垂直或水平捲動。」
- 只讀三份原始 Excel，不讀寫三合一版本，不覆寫原始檔。
- 目前目錄不是 Git repository。直接於 `D:/duck` 建立獨立 `inventory_app` 資料夾；不為完成技能中的 commit 步驟擅自初始化 Git。每項任務保存檔案及驗收結果即可。
- 所有時間由 `Asia/Taipei` 業務日期判斷，測試以注入日期固定結果。部署方式、多人帳號及收銀串接不在本次實作範圍。

## Review Focus

1. 舊資料含撞號與同名異規格：匯入不能誤合併；Task 3 測試。
2. 同商品有已知、未知與過期批次：總覽不可把部分加總冒充完整總量；Task 2 測試。
3. 連點提交、兩個分頁同時出貨：只能入帳一次，庫存不能負數；Task 2、5 測試。
4. 長品名、200% 字級、手機鍵盤及讀取失敗：資料可操作、錯誤可見，正常尺寸不長捲；Task 4、5、8 驗收。
5. 先匯出再改價、備份中途失敗：匯出版本狀態正確，失敗備份不可標記成功；Task 6、7 測試。

## 檔案配置與共用契約

全部產品程式位於 `inventory_app/`：

- `app/__init__.py`、`config.py`、`auth.py`：建立應用程式、設定與單帳號登入。
- `app/db.py`、`schema.sql`、`models.py`：連線、資料結構與輸入型別。
- `app/inventory.py`、`products.py`、`dashboard.py`：庫存、商品與總覽業務規則。
- `app/imports.py`、`media.py`、`exports.py`、`backups.py`：檔案邊界與資料保護。
- `app/api.py`、`templates/index.html`：API 與單頁外殼。
- `app/static/styles.css`、`app.js`、`views/*.js`：共用版型與四個功能。
- `tests/test_*.py`、`tests/fixtures/`：隔離暫存資料庫及小型自製測試檔。
- `requirements.txt`、`run.py`、`start.ps1`、`README.md`：依賴、啟動與簡短操作說明。
- `data/`：執行時資料庫、媒體與匯入暫存；`backups/`：備份。兩者不混入原始資料。

金額及數量 API 使用十進位字串或 `null`，業務計算用 `Decimal`。資料庫以十進位文字儲存，避免浮點累積；不可對此欄位直接以 SQL 浮點 SUM 計算。回應時間為含時區 ISO 8601。

`models.py` 定義 dataclass：`ReceiveCommand(product_id, quantity, cost, received_on, expires_on, unknown_expiry, saleable_confirmed, request_id)`、`IssueCommand(product_id, allocations, reason, request_id)`、`CountCommand(batch_id, actual_quantity, expected_version, request_id)`。數量／價格均為 Decimal，日期為 date 或 None；`allocations` 是含 batch_id、quantity、expected_version 的清單。

`Page` 字典固定包含 `items, total, page, page_size`；錯誤回應固定為 `{error: {code, message, fields}}`。所有異動 API 都要求登入、CSRF token 與 request_id。相同 request_id、相同內容回傳原結果；不同內容回傳 409。

## Task 1：應用程式、資料庫及登入

**Files:** 建立 `requirements.txt`、`run.py`、`app/__init__.py`、`config.py`、`auth.py`、`db.py`、`schema.sql`、`models.py`、`tests/test_app.py`。

**Interfaces:** `create_app(config: dict | None) -> Flask`；`connect_db(path: Path) -> sqlite3.Connection`；`init_db(connection) -> None`。資料表固定為 users、products、batches、movements、requests、invoice_items、invoice_exports、imports、media、backup_runs；商品版本為 products.version、批次版本為 batches.version。movements 保存異動原因、操作者、前後量與 reversal_of；requests 以 request_id 唯一鍵保存 payload_hash 及結果。後續任務沿用此結構。

- [ ] 建立 `.venv` 並安裝所列依賴，將實際採用版本固定於 requirements。現有工具環境有 Python 3.12.14、openpyxl 3.1.5、Pillow 12.3.0，但未裝 Flask；不可假裝已可啟動。
- [ ] 撰寫 `test_login_required`、`test_csrf_rejected`、`test_schema_preserves_null_quantity`；斷言未登入 API 為 401、缺 CSRF 的修改為 403、未知數量維持 None。
- [ ] 執行 `.venv\Scripts\python -m unittest tests.test_app -v`，確認因功能缺失而失敗。
- [ ] 實作上述介面及 schema；品號唯一、外鍵啟用。初始帳號透過本機初始化流程設定密碼，不提供固定預設密碼。cookie 為 HttpOnly、SameSite，部署 HTTPS 時啟用 Secure。登入錯誤使用一致訊息並限制重試。
- [ ] 重跑測試確認通過，保存檔案；原始資料不變。

## Task 2：批次、庫存異動與總覽計算

**Files:** 建立 `app/inventory.py`、`products.py`、`dashboard.py`、`tests/test_inventory.py`、`tests/test_dashboard.py`。

**Interfaces:** 使用 Task 1 連線與 command。提供 `receive(conn, command, actor_id) -> dict`、`issue(conn, command, actor_id, today: date) -> dict`、`count_stock(conn, command, actor_id) -> dict`、`reverse_movement(conn, movement_id, reason, request_id, actor_id) -> dict`、`list_products(conn, query, status, page, page_size, today) -> Page`、`get_dashboard(conn, today, page, page_size) -> dict`。總覽包含 `out_of_stock_products, low_stock_products, expiring_batches, uncounted_products, alerts, updated_at`。

- [ ] 撰寫測試：兩批 2、7 包合計 9；扣 3 包可分配 2+1；負數或不足出貨失敗且不留半套紀錄；空白批次保持未盤點；過期排除；今日到期與第 30 天即期、第 31 天正常。
- [ ] 加入測試：同 request_id 只扣一次；兩個連線以同版本扣貨僅一個成功；未知效期須確認可售；顧客退回預設不可售；沖銷若會產生負庫存則拒絕；瓶、包不合計為一個數量。摘要零量、低量、未知狀態不重複歸錯類別。
- [ ] 執行 `.venv\Scripts\python -m unittest tests.test_inventory tests.test_dashboard -v`，確認先失敗。
- [ ] 實作交易、異動與版本檢查。寫入以 SQLite transaction 序列化；先檢查請求去重，再檢查版本與庫存。新增商品、單位換算、修改售價由 products.py 提供 `create_product(conn, values, actor_id) -> dict`、`update_product(conn, product_id, values, expected_version, actor_id) -> dict`。
- [ ] 重跑測試通過。總覽計數按商品或批次定義，不採不同單位相加。

## Task 3：原始資料匯入及商品對應

**Files:** 建立 `app/imports.py`、`media.py`、`tests/test_imports.py`、`tests/test_media.py`。

**Interfaces:** `preview_import(paths: list[Path], staging_dir: Path) -> dict` 回傳 `import_id, products, batches, issues, price_cards, invoice_items`；`commit_import(conn, import_id, resolutions: dict, actor_id) -> dict`；`extract_media(xlsx_path: Path, staging_dir: Path) -> list[dict]` 回傳 sheet、anchor、original_path、thumbnail_path。對應決策以原檔、工作表、列／圖卡位置作鍵保存。

- [ ] 撰寫測試：176 筆來源列可追溯；同品號同商品不同效期形成批次；I11001、C19009 異品撞號產生待確認；空白庫存／價格保留 None；重複提交相同匯入不重建庫存。
- [ ] 加入測試：價格公式有快取時讀取快取、缺快取則待確認；未對應價目表圖卡與發票項目不遺失、不以近似名稱自動綁定；圖片解壓路徑不得超出 staging_dir。
- [ ] 執行 `.venv\Scripts\python -m unittest tests.test_imports tests.test_media -v` 確認失敗。
- [ ] 使用 openpyxl 唯讀讀取文字與值，另讀公式辨識缺快取狀態。以 ZIP/XML drawing anchors 擷取照片及對應線索，Pillow 建縮圖，原圖不壓縮覆寫。異常與衝突逐筆顯示；確認決策後同一交易提交。
- [ ] 重跑測試；對三份真實原檔執行唯讀預覽，對照 176 筆庫存列、18 張價目工作表與 96 筆發票項目。不自動提交猜測對應。

## Task 4：固定一頁外殼、總覽及查庫存

**Files:** 建立 `app/api.py`、`templates/index.html`、`static/styles.css`、`static/app.js`、`static/views/dashboard.js`、`inventory.js`、`tests/test_queries.py`。

**Interfaces:** `GET /api/dashboard?page=&page_size=`；`GET /api/products?q=&status=&category=&page=&page_size=`；`GET /api/products/<id>`；`GET /api/products/<id>/batches?page=&page_size=`。前端 `navigate(view, filters={})`、`openProduct(productId)`；視圖入口限 dashboard、inventory、catalog、history。

- [ ] 撰寫查詢測試：非法 page_size 拒絕或限制至 10；中文部分名稱查詢；缺貨摘要連到同條件清單；空結果與查詢錯誤分開。
- [ ] 執行 `.venv\Scripts\python -m unittest tests.test_queries -v` 確認失敗。
- [ ] 實作單一外殼與四入口，預設總覽；總覽四摘要、最多六筆待辦及三快捷操作。庫存每頁最多十筆，依實際容器高度縮減；不隱藏超出資料而不提供換頁。載入失敗保留錯誤及重試。
- [ ] 重跑 API 測試並使用可用瀏覽器工具實際檢查 1366×768、390×844。含長品名、空清單及大量資料；兩尺寸正常字級 document 不超出視窗，所有導覽與換頁控制可見。

## Task 5：商品面板與日常操作

**Files:** 建立 `static/views/product.js`、`operations.js`、`imports.js`、`tests/test_operations_api.py`；修改 `api.py`、`styles.css`。

**Interfaces:** `POST /api/receipts`、`/issues`、`/counts`、`/returns`、`/reversals`、`/products`；`PATCH /api/products/<id>`；`POST /api/imports/preview`、`POST /api/imports/<id>/commit`。呼叫 Task 2、3 介面，不在路由重複庫存計算。

- [ ] 撰寫 API 測試：數量與日期格式、空價格、NaN／Infinity、負數、小數單位限制、過期銷售、未選批次、重複提交、舊版本修改均有正確結果；錯誤為 400／409 並有繁體中文欄位訊息。
- [ ] 執行 `.venv\Scripts\python -m unittest tests.test_operations_api -v` 確認失敗。
- [ ] 實作商品面板內基本資料、批次、異動頁籤及短表單；手機必要時分步。出貨列出分配批次，盤點逐批輸入。跨檔對應及撞號確認置於匯入精靈，用分頁呈現，不能形成長表單。
- [ ] 儲存時禁止重複按鈕操作但保留伺服器去重；失敗保留輸入。開啟面板後移入焦點，關閉回到原按鈕；未儲存退出提示，完成操作更新總覽與當前清單。
- [ ] 重跑 API 測試，瀏覽器實際完成進貨、跨批出貨、盤點與改價。以窄畫面、200% 字級及鍵盤輸入驗證可用性，長內容僅局部捲動或換步。

## Task 6：價目表、發票匯出與異動查詢

**Files:** 建立 `app/exports.py`、`static/views/catalog.js`、`history.js`、`tests/test_exports.py`；修改 `api.py`、`styles.css`。

**Interfaces:** `GET /api/catalog?page=&category=`；`GET /api/history?page=&product_id=&kind=&from=&to=`；`POST /api/invoice-exports`；`GET /api/invoice-exports/<id>/download`。`build_invoice_xlsx(conn, destination: Path) -> dict` 回傳 `export_id, product_revision, row_count, issues`，有阻擋問題時不產生誤導檔案。

- [ ] 撰寫測試：匯出精確七欄、純值、品號保留文字、原始稅別保留；缺價阻擋且不轉零；蔬菜固定項目保留；單位價格一致；未確認對應列出問題。
- [ ] 加入測試：改價使待匯出標記更新，匯出快照與當時版本一致，再改價後舊檔維持原內容；前端價格修改後讀新值。
- [ ] 執行 `.venv\Scripts\python -m unittest tests.test_exports -v` 確認失敗。
- [ ] 實作發票輸出為可由 openpyxl 重新讀取的七欄 XLSX；保持 source 稅別值與分類對應，不提供實際開票行為。下載檔以 opaque ID 控制，不接受任意路徑。價目表畫面分頁預覽，列印 CSS 可輸出完整內容、隱藏導覽。
- [ ] 重跑測試，回讀輸出驗證七欄、文字品號及價格；在瀏覽器檢查單頁預覽與列印預覽，未設定價格／未知庫存有明確文案。

## Task 7：備份、還原與本機啟動

**Files:** 建立 `app/backups.py`、`tests/test_backups.py`、`start.ps1`、`README.md`；修改 `run.py`、`config.py`。

**Interfaces:** `create_backup(db_path: Path, media_dir: Path, backup_dir: Path) -> Path`；`restore_backup(archive: Path, destination: Path) -> None`；`backup_due(now, last_success) -> bool`。restore 僅還原到新的空目錄，正式切換資料須先關閉應用程式。

- [ ] 撰寫測試：SQLite backup 快照與圖片完整還原；失敗不更新成功時間；暫存半成品不可被當有效備份；含穿越路徑 archive 拒絕；一天僅一次成功自動備份。
- [ ] 執行 `.venv\Scripts\python -m unittest tests.test_backups -v` 確認失敗。
- [ ] 實作應用程式運行時每日備份，啟動時補執行到期備份；電腦關閉期間不承諾備份。媒體檔案不可變命名，備份完成前不刪原圖。備份先寫暫存檔，驗證 manifest 後再更名。
- [ ] 啟動器使用 Waitress 綁定 127.0.0.1，關閉 debug；首次初始化引導設定帳密。不要啟用公網監聽。操作說明涵蓋啟動、匯入確認、備份失敗提示及還原步驟。
- [ ] 重跑備份測試，實際還原到暫存目錄驗證商品／批次／圖片／異動一致。

## Task 8：整合驗收與交付

**Files:** 建立 `tests/test_workflow.py`、`docs/verification.md`；按驗收結果修正產品檔案。

**Interfaces:** 沿用前述 API 與啟動器，不新增第二套業務規則。

- [ ] 寫整合測試：登入 → 匯入小型已確認資料 → 2+7 批次 → 出貨 3 → 盤點 → 改價 → 發票匯出 → 備份還原。斷言每一步庫存、價格與異動筆數符合操作。
- [ ] 執行 `.venv\Scripts\python -m unittest discover -s tests -v`。測試先證實缺漏流程，再修正至通過；不能用快取／靜態示意畫面當成功證據。
- [ ] 瀏覽器驗收四功能在兩個指定尺寸不長捲，換頁不漏資料；斷網／API 錯誤保留可重試狀態，不顯示假零。列印價目表可包含全部頁面。
- [ ] 正式原檔僅產生匯入預覽，未獲確認的衝突不擅自變成正式庫存；可用獨立測試資料展示完整流程並清楚標示示範資料。
- [ ] 執行一次完整測試、記錄真實結果與未驗證項目；原始資料檔案雜湊與實作前一致。完成獨立程式碼檢查後交付啟動方式與本機預覽。

## 技術依據與執行方式

Flask 正式使用應採專用 WSGI server，即使只有本機單一使用者也不使用 development server，依 [Flask 部署文件](https://flask.palletsprojects.com/en/stable/deploying/)。其餘依賴版本以實作環境安裝與驗證結果鎖定。

建議由目前助理直接依序實作：資料規則與三個業務功能緊密相依，同一個實作者較容易維持一致；最後進行獨立整體檢查。先由使用者審閱本計畫並確認直接實作方式，再開始產品程式。
