# 菜騎鴨雲端部署與資料庫安排

日期：2026-10-01。狀態：部署設計，尚未改造或上線雲端版本。

## 已確認的需求

- 保留 Python／Flask 與現有簡約、一頁式介面，供單店老闆登入管理。
- 原始 Excel 唯讀。使用者已指定庫存管理表為目前售價來源。
- 免費額度優先；使用者接受 Google Cloud 計費帳戶及限制用量，未授權任意升級付費方案。
- 採 Cloud Run 執行網站，Supabase Free 提供 PostgreSQL 與私有圖片儲存。
- 網址使用 Cloud Run 提供的 HTTPS 網址，起步不購買網域。

## 現況與邊界

本機目前已接入 173 項商品、176 筆批次、186 張價目卡、96 筆發票項目。56 張價目卡、14 筆發票已核對連結；9 筆蔬菜價格系列為獨立固定發票項目。130 張卡與 73 筆發票仍待核對，不把來源缺漏假裝成完成。

本機使用 SQLite，圖片約 146.47 MiB。既有網站不能原封不動放上 Cloud Run：容器檔案會隨實例消失，SQLite、圖片、密鑰及備份都不能依賴容器磁碟。[Cloud Run 執行契約](https://docs.cloud.google.com/run/docs/container-contract)

發票和庫存採不同編碼。例如 B10001 在發票表是柴魚片，在庫存表是豬五花，不能用品號直接 JOIN。本次已修正本機發票匯出，保留發票平台原編號，售價取商品主檔，並補回歸測試；雲端版本須保留此行為。對應確認前，不使用匯出檔更新發票平台。

## 架構

瀏覽器 → Cloud Run（Flask、登入、業務驗證）→ Supabase PostgreSQL／私有 Storage。

- Cloud Run 提供同源頁面及 API，保留現有操作流程。
- PostgreSQL 是正式庫存唯一寫入來源；本機在正式切換後只作備份／測試，不提供離線同步，避免出現兩套庫存。
- 私有 Storage 保存產品原圖、縮圖與備份；圖片透過登入後的短效簽名 URL 存取。
- 所有進出貨、盤點、改價都經後端與資料庫交易，瀏覽器不取得管理金鑰。
- 資料表放在不對公開 Data API 開放的 schema；應用程式使用專用最小權限角色，遷移另外使用管理角色。

## 正規化資料模型

| 資料表 | 責任與關聯 |
| --- | --- |
| categories / suppliers / units | 分類、供應商、計量單位字典，各以獨立 ID 引用，保留原分類／供應商編碼 |
| products | 一個可獨立管理庫存的規格一筆；唯一內部 SKU，分類／供應商／單位外鍵、名稱、售價、最低庫存 |
| batches | 商品外鍵、数量、進價、進貨日、效期、可售確認；相同商品不同效期各自保留 |
| product_sources | 檔案雜湊、工作表／行或儲存格、原品號／名稱／單位／售價、商品 ID；原始值不可被目前售價覆蓋 |
| catalog_cards | 原圖卡及規格、來源售價、可空的商品對應、價格模式；不同包裝不可冒充相同庫存單位 |
| invoice_items | 發票平台原分類／編號／稅別／單位／原售價、可空的商品對應；固定價格系列獨立保存 |
| movements | 進出貨／盤點／價格變更前後值、操作者、時間、原因及沖銷參照；不刪歷史 |
| import_runs / import_issues | 匯入檔案雜湊、批次、問題、處理決策及核對狀態，避免重复匯入 |
| users / requests / backup_runs / invoice_exports | 帳號、冪等請求、備份和匯出版本 |

金額與數量採 NUMERIC，允許六位小數；空白庫存、售價與日期使用 NULL，絕不補 0。日期採 DATE，操作時間採 TIMESTAMPTZ，畫面以 Asia/Taipei 顯示。kg/Kg 合併為 kg；包、瓶、罐、盒、手不擅自互換。

所有批次更新保留版本條件，跨批次扣庫存以固定 ID 順序鎖定資料列，整筆交易成功才入帳。請求 ID 有唯一限制；同 ID 不同內容拒絕，同 ID 相同內容回傳既有結果。不能僅把 SQLite 的問號換成 PostgreSQL 參數就視為遷移完成。

## Cloud Run 起始設定

- request-based billing；min instances 0，service-level max instances 1；1 vCPU、512 MiB，concurrency 4，timeout 60 秒。容量需以真實資料壓測驗證。
- 監聽 0.0.0.0:$PORT；正式環境不在啟動時自動建立 SQLite，也不自動執行 schema migration。
- 連線使用 Supabase transaction pooler，小型連線池，TLS 並驗證伺服器憑證；使用 psycopg 時關閉不適用的 prepared statements。[連線方式](https://supabase.com/docs/guides/database/connecting-to-postgres)
- 部署區域優先與 Supabase 同區，暫定新加坡；建立前確認兩邊實際可用區域與免費方案額度。
- SECRET_KEY、資料庫密碼、Storage 金鑰由 Secret Manager 注入，禁止寫進映像或版本庫。正式帳號須在公開服務前建立完成，關閉初次管理員註冊。
- SESSION_COOKIE_SECURE 開啟，登入限流狀態持久保存；只信任已配置的代理標頭。
- 將 .venv、.qa、原始 Excel、SQLite、備份、secret.key 排除於建置內容。原始 Excel 只在本機處理，遷移清洗後的資料和媒體。

## 費用控制與限制

Cloud Run request-based 定價目前包含每月 200 萬請求，以及 CPU、記憶體免費額度；是否零元仍取決於區域和所有相關服務的實際用量。[Cloud Run 定價](https://cloud.google.com/run/pricing)

Supabase Free 目前提供 500 MB 資料庫、1 GB Storage，連續一週沒有活動的專案可能暫停。不以人造請求規避暫停；超出額度時先通知使用者，不自動升級。[Supabase 定價](https://supabase.com/pricing)

- 設定帳單通知及適用的 Cloud Run spend cap。spend cap 目前屬 Preview，且不涵蓋所有其他 Google Cloud 服務；實際金額由帳號持有人在啟用前填定。[計費與 spend cap](https://docs.cloud.google.com/run/docs/configuring/billing-settings)
- max instances 是資源限制，不是帳單硬上限，短暫情況也可能超出。[實例限制](https://docs.cloud.google.com/run/docs/configuring/max-instances)
- 建置、映像倉庫、網路、Secret Manager、排程／Job 與備份容量須一起核算。清除舊映像並限制日誌保留，不把免費運算等同所有服務免費。
- 不建立 Cloud SQL、常駐 VM 或 VPC connector；不配置 min instances 1。

## 備份與移轉

本機匯入前後均已產生包含 DB 與圖片的驗證 ZIP。雲端不可沿用背景執行緒每日備份，因 Cloud Run 閒置時不保證執行。

雲端採獨立排程備份工作，pg_dump 加媒體清單／雜湊，每天一份、保留七份資料庫備份，原圖僅保留去重的一份；備份寫入私有儲存並定期下載至店家電腦。排程和 Job 的實際免費額度／費用在建立前核對。Supabase Free 不提供可下載的託管資料庫備份，須自行維護。[正式使用檢查](https://supabase.com/docs/guides/deployment/going-into-prod)

移轉步驟：停止本機寫入 → SQLite 一致性備份 → 清洗／來源對照 → PostgreSQL migration → 匯入並重設序號 → 上傳圖片／核對雜湊 → 核對每批數量和日期／NULL → 測試登入與交易 → 開放正式網址。失敗時回到本機；一旦雲端產生新交易，不直接用舊 SQLite 覆寫。

## 實作與驗收順序

1. 建立 PostgreSQL schema migration 與本機資料轉入工具，保留 SQLite 本機版。
2. 改造資料庫存取、鎖定、版本衝突、冪等請求與發票原編號保留。
3. 改造 Storage、雲端匯出下載、Secret 管理及登入限流。
4. 加入容器建置、環境檢查、部署設定及獨立備份工作。
5. 在真實 PostgreSQL 上測試兩個請求同時扣庫存、重試、交易回滾、沖銷、migration 重跑和備份還原。
6. 在雲端測試容器重啟後資料／圖片／登入有效性、桌機手機一頁式介面，再切換正式寫入。

這份設計不代表上述改造已完成。現階段缺少已授權的 Google Cloud project ID、Supabase project reference／地區與安全的憑證設定。不可在聊天訊息中貼資料庫密碼或管理金鑰。
