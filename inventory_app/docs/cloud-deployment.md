# Cloud Run 上線紀錄與操作

## 2026-10-03 Claude 修改審查與部署

- 以先前正式版本的建置來源 ZIP 比對工作目錄，檢查 12 份修改檔及新增 `sales-date.js`。主要變更為跨日草稿日期、補登銷售提醒與確認、Excel 取消／已扣庫存列處理、盤點確認可售及相應篩選；沒有 schema 遷移。
- Python 測試 224 項：218 通過、6 項需專用 PostgreSQL 的整合測試略過；另 5 項 JavaScript 日期測試及全部前端 JavaScript 語法檢查通過。隔離瀏覽器實測盤點確認可售，以及補登後進貨批次的提醒、勾選確認、完成扣庫存流程。
- 以正式 PostgreSQL 強制唯讀交易驗證待確認可售篩選、補登銷售預覽及 Excel 銷售單號查核。正式庫存未用於寫入測試。
- 部署前備份 `duck-backup-5bppn` 成功。候選 `duck-inventory-claude-review-1003` 通過健康、匿名 API 防護與九份前端檔案雜湊檢查後切至 100% 流量；前版 `duck-inventory-workspace-1003` 保留。既有環境、Secret 引用、資源與服務帳號均未變更。
- 正式已登入頁面驗收 173 項商品、補登日期提醒、待確認可售篩選（2 項）與盤點確認選項正常；沒有在正式環境儲存測試盘點或送出測試銷售單。未重跑 Google OAuth 流程。

## 2026-10-03 店務介面與 Excel 匯出升級

- 正式版本 `duck-inventory-workspace-1003` 已接收 100% 流量，正式網址不變。先以 `workspace-preview` 標籤建立零正式流量候選版本，檢查後切換流量並移除臨時標籤；前版 `duck-inventory-manual-key-v2` 保留供程式回退。
- 本次上傳工作目錄的程式修改：停用 LINE 接單入口、保留獨立 Excel 匯入、新增每日銷售草稿／歷史單 Excel 匯出、分類圖示、固定篩選與商品清單獨立捲動、底部較大頁碼與跳頁選單。沒有執行資料遷移或匯入本機庫存。
- 更新前備份 `duck-backup-9bd96` 成功。既有環境設定、Secret 引用、服務帳號、1 CPU／1 GiB、最多 1 執行個體、並行數與逾時設定均比對不變。
- 本機測試 215 項：209 通過、6 項專用 PostgreSQL 整合測試略過。候選及正式網址 `/health` 成功，匿名管理 API 回 401；七份前端檔案 SHA256 與部署來源一致。
- 以既有已登入工作階段驗收正式頁面：LINE 入口已移除，173 項商品載入、篩選圖示、第 5／7 頁跳轉正常；實際下載每日銷售草稿 Excel，核對品號、數量、草稿狀態與備註。測試草稿已清除，沒有送出銷售單、盤點或扣庫存。此驗收使用既有登入狀態，未重跑 Google OAuth 登入流程。

## 2026-10-03 LINE 接單雲端升級

以 `262e8be` 的 LINE 接單、每日銷售帶入與日期摺疊介面部署。先建立零正式流量候選版本，核對健康、匿名管理 API 被拒與前端檔案雜湊後切換流量。正式網址沿用不變。

- 升級前 `duck-backup-spbz9` 備份成功。新增遷移 `003_line_orders.sql`、`004_line_order_sales.sql`、`005_line_order_edits.sql`，checksum 逐檔相符；沒有匯入本機營運資料。商品 173 筆、批次 176 筆維持一致。
- 六張 LINE 資料表位於私有 `duck` schema，均啟用 RLS；`duck_runtime_access` 政策僅允許既有 `duck_runtime` 使用，`anon` 和 `authenticated` 沒有表格 SELECT 權。一次性部署 SQL 為 `deploy/line-orders-rls.sql`，適用本專案既有 runtime role；不要直接重跑已存在的 CREATE POLICY。
- OpenAI 新金鑰透過安全建立流程產生，Cloud Run 引用 `OPENAI_API_KEY=duck-openai-api-key:1`，`OPENAI_MODEL=gpt-6-luna`；只有既有服務帳號取得此 Secret 的讀取權。
- 正式登入後 LINE 接單、每日銷售頁面載入成功，從網站按「測試連線」顯示 OpenAI 連線成功。另用新金鑰與正式 JSON Schema 轉換一筆虛構訂單，1166 input tokens、147 output tokens；未匯入真實聊天或寫入正式訂單。
- 本機測試 194 項，188 通過、6 項需專用 migrator 的整合測試略過。RLS 備份相容性修正後，18 項備份測試全數通過。
- `pg_dump` 使用 `--enable-row-security --inserts`，配合 runtime 可讀取全部應用資料列的 RLS 政策，無須授予 BYPASSRLS。日後若改成逐列篩選政策，須重新驗證備份完整性；還原以管理員在隔離空白資料庫執行，並重設 runtime 權限。
- 原有 1 CPU、1 GiB、最少 0／最多 1 執行個體及 US$10 Cloud Run 上限保留。金鑰更新教學見 [Cloud Run OpenAI 金鑰](openai-cloud-run.md)。

## 2026-10-03 支出上限調整

依使用者要求，已於 Google Cloud 控制台將 `duck-inventory` 專案的 Cloud Run 每月支出上限由 US$5 調整為 **US$10**，儲存後清單確認「已設定」。名稱為「Cloud Run 每月 US$10 暫停」。

- 固定通知門檻為 50%、80%、100%，分別為 US$5、US$8、US$10；電子郵件通知帳單管理員、帳單使用者及專案擁有者。
- 此設定僅適用 Cloud Run，按未扣除優惠的預估費用追蹤；達上限會觸發暫停，但有執行延遲，可能產生超額費用。其他 Google Cloud 服務費用不在此上限內。
- 帳單帳戶另一筆原有的 $5 通知預算未變更。下方 US$1 記載屬早期歷史設定，以本節為準。

## 2026-10-03 每日銷售版升級

在 `codex/daily-sales-cloud` 整合每日銷售與原雲端部署分支。新增 `002_daily_sales.sql`，使用既有 `duck_runtime` 帳號，不重建或覆寫正式資料庫。客人下單預設關閉；首頁改為每日銷售、第二頁為商品管理，保留 Google 登入與帳號授權。

- 升級前雲端備份 `duck-backup-8lkjh` 成功。比對時雲端已有 21 筆不同於本機的批次數量及 462 筆異動；保留雲端庫存、價格、帳號、規格及既有人工對應。只更新 11 個商品照片與 7 個價目卡照片，逐物件核對上傳內容。沒有匯入本機舊庫存，也沒有在正式庫存送出測試銷售單。
- 三份 Excel 由下載請求觸發，從單一 PostgreSQL repeatable-read 快照生成。匯出頁提供庫存表與三份 ZIP；原始價目表全部照片與版型保留。店家仍需每日下載至自己的電腦，雲端不會自動寫入本機資料夾。
- 原始價目表約 150 MB，依 SHA256 分為 18 個不可變物件放在既有私人 bucket 的 `templates/`；`metadata.excel_template` 保存完整雜湊與分段清單。冷啟動會重新組回並驗證，容器磁碟僅作可重建快取。保留原始 Excel 作獨立備援；現有資料庫備份工具的完整媒體下載不包含這些範本分段，重建範本時使用原始 Excel。
- ZIP 採串流下載，避免 Cloud Run 非串流 HTTP/1 回應的 32 MiB 限制。`00003-xiq` 候選版本因此驗收失敗，未切正式流量；修正後候選版本為 `00004-siz`。
- 記憶體為 1 GiB，以容納含照片範本、三份輸出及 ZIP 暫存；請求上限 300 秒、並行 4、CPU 1、最少 0／最多 1 實例，仍維持按請求計費。沒有增加 Cloud SQL、VM 或付費 Supabase；原費用暫停設定不變。
- 本機測試 170 項：164 通過、6 項需專用 migrator 的既有整合測試略過。另外於真 Supabase 的獨立空白 schema 實測新增表、ID 回傳、整單扣庫存、並行同請求只扣一次、沖銷及過期預覽回滾，通過後清除合成測試表與空 schema。
- `duck-inventory-00004-siz` 已接收正式 100% 流量，候選標籤已移除。以現有 Google 管理員完成實際選帳號與回站登入，正式頁面確認每日銷售為第一頁籤、分類按钮可重點取消、三份 Excel 備援入口可用。124 個商品照片路由全部成功。
- 真實下載 ZIP 150,165,714 bytes，約 59 秒；176 個批次數量逐筆與正式資料庫比對一致、96 筆發票商品，原價目表全部 178 個內嵌媒體內容雜湊相同。測試沒有正式扣庫存。驗收詳細 JSON 與下載檔保存在忽略的 `.qa/`。
- 本機 8765 沒有運作中的服務。日常正式資料以雲端為準；如有離線 Excel 盤點，恢復後需人工核對差異，不能直接拿舊本機資料庫覆蓋雲端。
- 備份工作映像已更新為相同版本，部署後 `duck-backup-2lhwg` 完整執行成功（約 1 分 51 秒）。保留前版 revision，若需回退程式可將流量切回；新增資料表保留，不能以回退程式為由覆寫新庫存。

以下為前一版本的歷史部署紀錄，顧客下單與 512 MiB／60 秒設定已由上述版本取代。

2026-10-02：資料搬移與 Cloud Run 第二版部署完成，正式 HTTPS 網址已公開，Google 帳號回站登入待本人確認。本機 8765 服務已停止，原始 Excel、SQLite 與照片保留作切換前快照；正式操作改用雲端，避免兩邊寫入。

- 店家後台：https://duck-inventory-953640890149.asia-southeast1.run.app/
- 顧客商店：https://duck-inventory-953640890149.asia-southeast1.run.app/shop
- 資料庫與照片：Supabase 專案 `jclgcdwqodblvmwkddau`，Singapore，Free。

## 費用與必要帳號

- Google Cloud 專案 `duck-inventory`（953640890149），已驗證計費帳戶連結。
- Supabase 免費專案、私有 schema 與 bucket 已建立。
- 使用者已在控制台建立 Cloud Run 每月暫停門檻，並確認實際幣別 USD、金額 1；API v1 僅列出另一筆舊的 TWD 5 通知預算，不能用它判定這筆 spend cap 幣別。
- 在 Billing → Budgets & alerts → Create budget，選 **Spend cap enforcement**，單一專案 `duck-inventory`、服務 Cloud Run、Monthly、金額 1 USD。若帳戶幣別不同或介面拒絕此金額，先確認等值門檻與支援情況，不能宣稱已生效。
- 官方目前標示此功能為 Preview；50%、80%、100% 通知，自動暫停後需人工解除。估算可能按未扣抵優惠金額觸發，並非「免費額度用完」計數器；有延遲且不涵蓋 Cloud Build、Artifact Registry、Secret Manager 等其他服務。另為整個專案建立費用通知，保留少量映像版本並檢查儲存費用。
- 閒置最少 0、服務與版本最多 1 實例，1 CPU、512 MiB、同時 4 請求、60 秒；這些是用量限制，不是金額硬上限。不自動解除 spend cap、不開 Cloud SQL / VM / VPC connector、不升級 Supabase 付費方案。

## 資料與認證

- PostgreSQL 私有 schema `duck` 保存庫存、訂單、帳號與來源紀錄。不要把 schema 加到 Supabase Data API exposed schemas。
- `duck_runtime` 是獨立 LOGIN 角色，僅授予該 schema 使用與資料 CRUD／序列權限；遷移使用管理員連線，網站不能建立或刪除資料表。
- Supabase 建立私有 bucket `duck-private`，圖片、匯出與備份透過後端同來源路由讀取。不要改成公開 bucket。服務金鑰僅置於後端 Secret Manager。
- Cloud Run 本機檔案只作暫存。`CLOUD_MODE=true` 缺少必要設定會拒絕啟動，不自動建立 SQLite 或遷移資料表。
- Google 登入使用現有 OAuth Web client，在 Google Console 加入正式 HTTPS `/auth/google/callback` 回呼。測試狀態需把每位店家加入測試使用者；顧客不需登入。
- 應用程式服務帳號 `duck-runtime` 只取得指定四個 Secret 的 secretAccessor 權限，不授與專案 Editor。不把憑證放進 Git、建置環境變數或 Docker image。

## 發佈順序

1. 完成計費、US$1 spend cap、整個專案通知；建立 Supabase 免費專案與私有 bucket。CLI 使用操作者自己的 Google 授權，不使用網站 Google 登入憑證。
2. 以管理員連線建立獨立 runtime role，保存密碼至本機忽略目錄。Runtime DSN 使用 TLS `sslmode=require` 或更強，選可從 Cloud Run 連線的 Supabase pooler；備份使用 direct/session pooler，不用 transaction pooler。
3. 先對隔離 QA schema 執行真 PostgreSQL 測試（環境變數 `TEST_POSTGRES_URL`），驗證鎖定、重試、拒绝超賣、權限與還原。測試不得指向正式 schema。
4. 維護時間停止本機寫入，產生一致 SQLite 備份與照片清單；保留原始檔不覆寫。`tools.migrate_postgres` 只接受空目標並驗證資料／ID，`tools.migrate_media` 比對 hash 後上傳。實際 CLI 參數使用各工具 `--help`。憑證透過環境或檔案安全載入，不貼到聊天。
5. 遷移完成後取得資料表逐筆比對結果、媒體 hash 比對、備份及隔離還原證據；建立 Secret Manager 版本，使用 `deploy/secret-versions.example.json` 的數字版本引用。
6. `deploy/environment.example.json` 複製至忽略的 `.qa` 設定位置，填入非機密設定及正式回呼。可使用 Cloud Run 專案編號確定性網址，在部署前向控制台確認並註冊；不得猜測網址後宣稱登入可用。
7. 啟用必要 Run、Build、Artifact Registry、Secret Manager API，設定專用 runtime 與 build 身分所需的最小權限。`deploy/deploy.ps1` 使用 source build；上傳清單應只含程式／樣式／模板／requirements／cloud entrypoint，不能有 data、Excel、secret、venv 或 QA。
8. 發佈後驗證 `/health`、`/shop`、Google 管理員登入、未登入管理 API 被拒、圖片授權、顧客下單與店家確認；再以新 revision 證明資料和照片仍存在。網站及本機不可同時接受正式寫入。

## 備份與故障

「設定 → 立即備份」啟動獨立 Cloud Run Job `duck-backup`，網頁顯示已排入，完成後更新備份時間。工作使用專用 GCP 身分，只讀取資料庫與 Storage 的兩個 Secret；一個 task、無自動重試、15 分鐘逾時。網站身分只有此 Job 的執行權限。備份預設使用 runtime DB 連線（含 schema_migrations 唯讀權限），可另設 `BACKUP_DATABASE_URL`；pg_dump 版本必須等於或新於伺服器大版本（映像目前用 17）。

目前為手動備份，未設定每天自動執行：每天重新讀取全部照片會耗用約 4.3 GiB/月的儲存流量。備份含 PostgreSQL dump 與不可變照片的雜湊清單，保留最近七個有備份的日期；照片另存於同一私有 bucket。需要異地副本時，以 `tools/cloud_backup.py download` 下載完整且驗證過的還原包。

## 驗收紀錄（2026-10-02）

- SQLite → PostgreSQL 逐筆比對通過：173 商品、176 批次、433 異動、186 價目卡、96 發票項目、3 道料理、1 管理員；原始訂單為 0 筆。
- 348 照片檔（含縮圖）共 153,582,597 bytes，上傳後全部內容雜湊比對成功。113 個不同的商品照片引用；原始資料沒有照片的商品不補造圖片。
- 本機 135 項測試通過；另六項真實 PostgreSQL 測試完成。隔離 QA schema 的 pg_dump / pg_restore 測試比對 22 表、20 筆合成資料與序列成功，未還原覆寫正式資料。
- 第二版 `duck-inventory-00002-6bw` 私有檢查通過：健康、顧客頁、173 商品、料理、Google HTTPS 導向、管理 API 拒絕匿名、三張不同商品照片內容吻合。九個管理 API 已使用搬移後的資料庫驗證。
- 使用者已儲存正式 OAuth callback；完整 Google 選帳號→回站登入仍待本人實測。
- 顧客接單設定保持原值：尚未開放。正式接單前，店家需完成有效庫存盤點、設定取貨時段並啟用接單。
- 代理 IP 防偽的 Waitress 單元測試已通過；Cloud Run 實際應用收到的 IP 尚未另設診斷端點驗證。新增 CDN/負載平衡器前必須重新核對代理層數。
- 首次雲端備份 `duck-backup-mlvcr` 成功；備份 ZIP 92,139 bytes，PostgreSQL dump 108,495 bytes，348 個物件清單與切換快照全部 hash 一致。已另下載私人 dump／manifest 副本；正式資料 dump 尚未作全量還原演練，上述還原測試使用隔離合成資料。
- 開放公開存取後重新驗證：`/health`、後台登入頁、顧客頁與商品／料理 API 正常；匿名管理 API 回 401；Google 導向含正確 HTTPS callback；商品圖片可讀，私人管理圖片路由拒絕匿名。

若超過門檻，網站會停止提供服務，但 Supabase 資料仍保留。不要自動解除暫停；檢查費用來源後再由管理員決定。Supabase Free 可能因長期無活動而暫停，需由管理員恢復；不以假流量規避。

參考：[Google spend caps](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)、[Cloud Run 容器限制](https://docs.cloud.google.com/run/docs/container-contract)、[Supabase Free 暫停](https://supabase.com/docs/guides/platform/free-project-pausing)。
