# 菜騎鴨外送道路距離查詢

輸入地址、定位或在地圖選點，依店家出發的汽車道路路線判斷外送：5 公里內低消 300 元；超過 5 至 10 公里須確認店家人手；超過 10 公里因人手不足無法配送。已移除原先的 3／5 公里直線範圍圈。

本目錄獨立於 Flask 庫存系統，不讀寫營運資料、不受理訂單。前端為 Vite + Leaflet，路線入口為 Vercel Node.js Function `api/route.js`。

## 本機預覽

需要 Node.js 22.12 以上（建議 24 LTS）。

```powershell
cd delivery-map
npm ci
npm run dev
```

開啟 http://127.0.0.1:4174 。未設定 Redis 時，本機 Vite 僅使用 OSRM，採單一程序每 1.1 秒最多一次限流，不允許 Google 呼叫。此例外不會進入 Vercel 正式 Function。

```powershell
npm test
npm run build
npm run preview
```

`dev` 與 `preview` 同用 4174 連接埠，請擇一執行。一般純靜態伺服器沒有 `/api/route`；Vite preview 已接本機 middleware。

## Google 優先、OSRM 備援

1. 後端驗證收貨點；店家起點固定，客戶不能指定 Google 參數或上游網址。
2. Google 兩把金鑰與共用 Redis 計數器就緒時，以原子 Lua 操作先預留一次用量。
3. 使用 Google Routes API 的 `DRIVE / TRAFFIC_UNAWARE`，取得道路公尺數與路線。不要求即時路況、機車路線或其他 Pro／Enterprise 功能。
4. 同一預留名額最多呼叫一次 Google Routes、一次 Maps Static。Google 路線畫在 Google 路線圖，完整保留 logo 與 attribution。圖像由後端取得，金鑰不進前端；不寫磁碟、不建立 CDN 快取。
5. Google 未設定、預算不足或出錯時，切換 OpenStreetMap / OSRM，在 Leaflet 畫出道路軌跡，清楚標示來源可能與 Google 不同。失敗的 Google 請求不退還計數、不自動重試。
6. OSRM 公開服務由 Redis `SET NX PX` 限制全站每 1.1 秒最多一次。Redis 連不上時不呼叫 Google，也不繞過 OSRM 公開服務限流；顯示無法判定與免費 Google 導航連結。絕不以直線距離冒充道路結果。

Google 路線圖是不可拖曳的靜態圖；按「調整收貨位置」回到互動選點地圖。這讓路線與地圖請求都由後端計數，不暴露可被繞過計數器呼叫的 Google 瀏覽器金鑰。OSRM 地圖維持拖曳、縮放及正射影像切換。

## 啟用設定

完整步驟見 [Google／Redis 設定說明](docs/google-osrm-setup.md)。參照 `.env.example` 將值填入 `.env.local`，不要覆蓋現有 Vercel OIDC 設定。正式環境在 Vercel 專案的 Environment Variables 設定。

| 變數 | 用途 |
|---|---|
| `GOOGLE_ROUTES_API_KEY` | 限定 Routes API 的伺服器金鑰 |
| `GOOGLE_STATIC_MAPS_API_KEY` | 限定 Maps Static API 的伺服器金鑰 |
| `UPSTASH_REDIS_REST_URL` | 共用持久化 Redis 的 HTTPS REST 網址 |
| `UPSTASH_REDIS_REST_TOKEN` | Redis REST 憑證，只放後端 |
| `GOOGLE_MONTHLY_LIMIT` | 每月 Google 配對請求上限，預設／最高 9,000 |
| `GOOGLE_DAILY_LIMIT` | 每日 Google 配對請求上限，預設／最高 250 |
| `OSRM_BASE_URL` | 預設 `https://routing.openstreetmap.de/routed-car`；可替換為自架 HTTPS OSRM 汽車服務 |

Redis 必須先由管理者初始化；不存在或損毀的用量帳本不會自動從零重建。無金鑰的 OSRM 模式仍需 Redis，以限制公開服務用量。不要刪除 Redis 帳本或設定到期時間。

### 免費額度邊界

- 截至 2026-10-03，Google Compute Routes Essentials 與 Maps Static 各有每月 10,000 次免費額度，按 SKU、帳務帳戶合併計算。本程式預設上限 9,000，另有每日 250 次限制（31 天最多 7,750 次），不是 Google 官方免費額度本身。
- 計數採美國太平洋日期；帳本跨月自動歸零。預留後即使發生網路錯誤仍計數，避免未知計費結果被當成免費。
- 這是本應用程式的請求限額，不是 Google 帳戶的零費用保證。同帳務帳戶其他專案、其他程式或外洩金鑰的用量不由此程式掌握。必須扣除既有用量、保留相應額度，並設定 Google Cloud 可用的 API 配額與預算通知。預算通知不會自動停止計費。
- Vercel、Redis、圖磚與地址服務各有自己的免費額度及條款；不能因 Google 有備援就認定所有服務無限免費。
- OSRM 公開服務僅供低流量示範，無可用性保證，禁止大量呼叫；流量成長時須自架或使用適合的託管服務。

## 距離與介面

- 起點：`24.2739442, 120.5453111`，菜騎鴨，臺中市清水區中社路 102-21 號。
- 分類用供應商原始公尺數：5,000 公尺屬可送；10,000 公尺屬須確認。顯示向上取到 0.01 公里，避免剛超界卻看起來在界內。
- 汽車路線不等同機車路線，也不保證與 Google Maps App 在不同時間／設定下所選路線相同。
- OSRM 限定起終點附近 100 公尺內有道路。定位誤差超過 100 公尺時先要求確認位置，不用直線誤差推算道路界線。
- 為限制濫用，只查詢店家周圍 60 公里內的點；此直線檢查僅作查詢區域限制，不拿來判定外送。
- 地址搜尋沿用 Photon；道路查詢取消過期結果，重設／重新輸入不會被舊回應覆蓋。
- 未達低消、運費與團購計算方式尚未在新規則中確認，顯示請洽店家，不沿用舊的 100／300 元分級或 20 元運費。

## 部署

Vercel 專案：`lee851104s-projects/duck-delivery-map`。既有網址：https://duck-delivery-map.vercel.app/ 。Root Directory 使用 `delivery-map`，不要部署整份庫存系統。

```powershell
vercel env ls
vercel deploy
# 完成 Preview 上的 Google 與 OSRM 實測後
vercel deploy --prod
```

本版新增後端 Function，不能只上傳 `dist` 到靜態主機。正式與 Preview 應使用同一 Redis 帳本，避免每次部署或分支重新取得免費額度；若用獨立帳本，須由管理者另外分配同帳務帳戶的用量。

## 隱私與驗證

`public/privacy.html` 說明供應商收到的資料。路線採 POST、回應 `no-store`；程式不持久化住址、座標或路線，Redis 僅保存用量與限流鎖。供應商仍可能記錄請求。

`npm test` 包含邊界、來源切換、Google 錯誤及地圖失敗、預算失效、限流、道路吸附限制、請求驗證與憑證不外洩。模擬測試不代表 Google 金鑰、帳務與 Redis 已啟用，仍須完成設定文件中的實際連線驗證。

2026-10-03 本機驗證：30 項測試及 Vite build 通過；瀏覽器實查 OSRM 清水車站 4.01 公里、沙鹿車站 7.31 公里、大甲車站 13.35 公里，分別顯示可送／須確認人手／無法配送。390px 手機與 1280px 桌面寬度無水平溢出，路線及起終點可見，瀏覽器未見錯誤。此為當次路線資料，未來道路更新可能改變數值。

2026-10-03 雲端驗證：Redis 原子並行整合檢查通過；Google Preview 實查清水車站取得 3,908 公尺及 Google 路線圖片。另一個 Preview 僅覆寫 `GOOGLE_MONTHLY_LIMIT=0`，同一位置回傳 OSRM 4,007.4 公尺及 `budget-limit`，Google 帳本前後均為 7，確認達限備援未增加 Google 計數。用量帳本依管理者確認的本月零既有用量初始化一次，後續測試預留名額均保留，不重設計數。

同日正式部署至 https://duck-delivery-map.vercel.app/ ，未登入瀏覽器實查清水車站，顯示「可以外送／道路 3.91 公里／低消 300 元」及完整 Google 路線圖；圖片載入正常，1280px 寬度無水平溢出，瀏覽器未見警告或錯誤。正式查詢後帳本為 8，保留所有測試預留名額。
