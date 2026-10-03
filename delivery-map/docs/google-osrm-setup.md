# 啟用 Google 路線與免費用量備援

現有專案已完成金鑰、Redis 與 Google／OSRM 預覽連線驗證；以下保留重新設定步驟。請勿把金鑰貼入對話或提交 Git。

## 1. Google Cloud

1. 在自己的 Google Cloud 專案啟用計費，啟用 **Routes API** 與 **Maps JavaScript API**。本版不使用 Places API、Google Geocoding API，也不再呼叫 Maps Static API。
2. Routes API 使用後端金鑰；Vercel 沒有固定出口時，不能填入網站網域當成它的 HTTP referrer 限制。另建 `GOOGLE_MAPS_BROWSER_API_KEY`，API 限制僅 Maps JavaScript API，網站限制 `https://duck-delivery-map.vercel.app/*`。瀏覽器金鑰會傳到前端，不能當成保密的後端憑證；不得與 Routes 金鑰共用。Preview 與 localhost 未加入網站限制時，動態 Google 地圖會被拒絕，轉為 OSRM。
3. 查看當月同帳務帳戶這兩個 SKU 的既有用量，並確認沒有其他應用程式持續共用預留的免費額度。路線與 Dynamic Maps 分別以各自 SKU 的既有用量初始化獨立帳本。其他服務已占用額度時，降低本站上限。
4. 設定 Google Cloud 提供的 API 配額與預算通知作第二層保護。預算通知不是硬性停用開關。本程式固定基本汽車模式，不能直接改為機車而仍沿用汽車免費上限。

截至 2026-10-03：Compute Routes Essentials 每月 10,000 次免費，第一級超額 US$5／1,000 次；Dynamic Maps 每月 10,000 次免費，第一級超額 US$7／1,000 次。本程式分別限制每月 9,000 次、每日 250 次，互不挪用名額。計數器限制本站正常流程，不能保證外洩或直接重用瀏覽器金鑰的呼叫也受它控制；Google Cloud 的網站/API 限制與可用配額仍須保留。

### 已套用的用量上限（2026-10-03）

Vercel Production、Preview、Development 均明確設定路線及動態地圖各每日 250 次、每月 9,000 次，正式站已重新部署。Google Cloud 專案 `duck-delivery-map` 亦已儲存並確認以下每日配額：

| API / 配額名稱 | 每日上限 |
| --- | ---: |
| Maps JavaScript API / Map loads per day | 250 |
| Routes API / Directions - ComputeRoutes per request quota per day | 250 |
| Maps Static API / Requests with a signature per day | 0 |
| Maps Static API / Unsigned requests (if URL signing secret is defined) per day | 0 |
| Routes API / DistanceMatrix - ComputeRouteMatrix per-element quota per day | 0 |
| Maps JavaScript API / 3D Map loads per day | 0 |
| Maps JavaScript API / Maps Grounding Widget per day | 0 |

每日 250 次，即使 31 天全數用滿也只有 7,750 次，低於目前各 10,000 次的 Essentials 路線與 Dynamic Maps 免費月用量。網站任一計數器達限後改用 OpenStreetMap＋OSRM；Google Cloud 配額另外限制此專案直接呼叫。這不涵蓋同帳務帳戶其他專案的用量，也不抵銷設定前已發生的費用。配額與計費量可能有差異，因此仍保留餘裕；不得清零既有 Redis 帳本。

## 2. 共用 Redis

1. 建立持久化 Upstash Redis，確認選的是 **Free** 方案且符合帳號資格，不要為本工具升級付費方案。官方目前列出 Free 方案 256 MB、每月 500K commands，以建立時主控台條款為準。
2. 取得 `UPSTASH_REDIS_REST_URL` 與 `UPSTASH_REDIS_REST_TOKEN`，填入 Vercel 此專案的 Production 與 Preview 環境變數。重新部署後生效。
3. 將相同變數填入本機 `.env.local`，供初始化使用；保留原本其他設定，不要提交此檔案。
4. 執行初始化。下方 `0` 只適用於各 SKU 當月確實零使用量，否則分別換成該 SKU 已有使用量：

```powershell
npm run budget:init -- 0
# Dynamic Maps 需另外核對本月既有用量，再初始化獨立帳本：
npm run budget:init -- 0 dynamic-maps
```

命令只在帳本不存在時建立 `duck-delivery:v1:google`，不覆蓋已有帳本。帳本不能設 TTL、刪除或每次部署重建。若遺失，Google 保持停用，須核對 Google 既有用量再初始化。跨月由原子預留操作自動更新月份。

`dynamic-maps` 選項建立 `duck-delivery:v1:dynamic-maps`，同樣拒絕覆寫既有帳本。2026-10-03 管理者已確認 Dynamic Maps 當月零用量，初始化為 0；原路線帳本及歷史測試名額持續保留。地圖帳本遺失時不自動重建。

正式環境 OSRM 也需要 Redis。公開服務每秒最多一個請求，不能用 Vercel 每個實例各自的記憶體鎖冒充全站限流。Redis 故障時顯示手動 Google 導航連結；只有本機單一 Vite 程序容許無 Redis 的 OSRM 示範。

## 3. Vercel 環境變數

在現有 `duck-delivery-map` 專案的 Settings → Environment Variables 填入：

```text
GOOGLE_ROUTES_API_KEY             Routes API 金鑰
GOOGLE_MAPS_BROWSER_API_KEY       Maps JavaScript API 網站限制金鑰
GOOGLE_MAPS_MONTHLY_LIMIT         9000（未填採此預設）
GOOGLE_MAPS_DAILY_LIMIT           250（未填採此預設）
UPSTASH_REDIS_REST_URL            Redis HTTPS REST 網址
UPSTASH_REDIS_REST_TOKEN          Redis REST 憑證
GOOGLE_MONTHLY_LIMIT              9000
GOOGLE_DAILY_LIMIT                250
OSRM_BASE_URL                    https://routing.openstreetmap.de/routed-car
```

上限 `0` 可主動停用 Google；非法或超過內建最高值的設定也停用 Google。更改金鑰、Redis 或計數器時，必須維持同帳務帳戶已用額度的正確基準。

在 Google Cloud 使用金鑰的複製按鈕，貼上完整實際值，不能複製畫面上的遮蔽圓點。Vercel 儲存後無法從 Secret 顯示畫面取回原值；更新時須從 Google Cloud 重新複製。環境變數修改後須重新部署才生效。

## 4. 部署前驗證

1. `npm test` 及 `npm run build` 通過。
   Redis 設定後另執行 `npm run test:redis`，用隔離的暫存 key 驗證 20 個並行預留最多核發 5 個名額、跨月／每日重設及損毀帳本拒絕。此檢查不改正式帳本、不呼叫 Google。
2. 在網站限制允許的部署網域搜尋公開地標，例如清水車站。確認 Google 互動底圖可縮放拖曳、具有路線及完整 attribution，5 公里內低消 300 元。未列入限制的 Preview 只能驗證 API 與備援，不能當成 Google 瀏覽器金鑰成功的證明。
3. 確認 Redis `used` 增加 1；Google Cloud 實際使用紀錄可能延遲，稍後核對 SKU。
4. Preview 將 `GOOGLE_MONTHLY_LIMIT=0` 後重新部署。再查同一地標，確認顯示 OSRM、OpenStreetMap 路線且 Google 帳本不增加。不要為此清零既有帳本。
5. 驗證服務失敗會顯示無法判定及導航連結，不給直線距離結論。恢復設定後才發布正式版。

6. 在同一頁 Google → OSRM → Google，確認 Dynamic Maps 帳本只增加第一次的 1 次，路線帳本依每次 Google 路線查詢增加；拖曳縮放不增加兩個本站帳本。地圖建立前需先取得 `/api/map-session` 名額，名額不足或讀取失敗時不下載 Google SDK。Maps JS 載入／授權失敗時使用 OSRM；不重試已消耗的地圖名額。

## OSRM 服務限制

預設 FOSSGIS 公開汽車服務，適合目前低流量教學工具，並非無限流量或保證可用的備援。程式已限流並保留 OSM attribution 與「回報地圖錯誤」。流量上升時改填自架或託管 OSRM 的 HTTPS base URL，服務須使用 `/route/v1/driving/` 格式及汽車道路資料。

## 官方來源

- [Google 價目表](https://developers.google.com/maps/billing-and-pricing/pricing)
- [Routes 計費分類](https://developers.google.com/maps/documentation/routes/usage-and-billing)
- [Google 路線展示規則](https://developers.google.com/maps/documentation/routes/policies)
- [Maps Static 路徑參數](https://developers.google.com/maps/documentation/maps-static/start)
- [費用控制](https://developers.google.com/maps/billing-and-pricing/manage-costs)
- [Upstash REST API](https://upstash.com/docs/redis/features/restapi)
- [Upstash 定價](https://upstash.com/pricing/redis)
- [OSRM 使用政策](https://routing.openstreetmap.de/about.html)
