# 啟用 Google 路線與免費用量備援

現有專案已完成金鑰、Redis 與 Google／OSRM 預覽連線驗證；以下保留重新設定步驟。請勿把金鑰貼入對話或提交 Git。

## 1. Google Cloud

1. 在自己的 Google Cloud 專案啟用計費，啟用 **Routes API** 與 **Maps Static API**。本版沒有使用 Maps JavaScript API、Places API、Google Geocoding API。
2. 建立兩把後端金鑰，分別限制只能呼叫 Routes API、Maps Static API。Vercel 一般沒有固定出口 IP；若沒有固定出口，不能填入網站網域當成伺服器金鑰的 HTTP referrer 限制。金鑰僅保存在 Vercel 後端；若需固定 IP 限制，使用支援固定出口的部署方式。
3. 查看當月同帳務帳戶這兩個 SKU 的既有用量，並確認沒有其他應用程式持續共用預留的免費額度。初始化計數使用兩個 SKU 既有用量中較大的值。其他服務已占用額度時，降低本站上限。
4. 設定 Google Cloud 提供的 API 配額與預算通知作第二層保護。預算通知不是硬性停用開關。本程式固定基本汽車模式，不能直接改為機車而仍沿用汽車免費上限。

截至 2026-10-03：Compute Routes Essentials 每月 10,000 次免費，第一級超額 US$5／1,000 次；Maps Static 每月 10,000 次免費，第一級超額 US$2／1,000 次。本程式以每月 9,000 個配對名額及每日 250 次保留餘裕。

## 2. 共用 Redis

1. 建立持久化 Upstash Redis，確認選的是 **Free** 方案且符合帳號資格，不要為本工具升級付費方案。官方目前列出 Free 方案 256 MB、每月 500K commands，以建立時主控台條款為準。
2. 取得 `UPSTASH_REDIS_REST_URL` 與 `UPSTASH_REDIS_REST_TOKEN`，填入 Vercel 此專案的 Production 與 Preview 環境變數。重新部署後生效。
3. 將相同變數填入本機 `.env.local`，供初始化使用；保留原本其他設定，不要提交此檔案。
4. 執行初始化。下方 `0` 只適用於當月兩個 SKU 確實零使用量，否則換成已有使用量中較大的數字：

```powershell
npm run budget:init -- 0
```

命令只在帳本不存在時建立 `duck-delivery:v1:google`，不覆蓋已有帳本。帳本不能設 TTL、刪除或每次部署重建。若遺失，Google 保持停用，須核對 Google 既有用量再初始化。跨月由原子預留操作自動更新月份。

正式環境 OSRM 也需要 Redis。公開服務每秒最多一個請求，不能用 Vercel 每個實例各自的記憶體鎖冒充全站限流。Redis 故障時顯示手動 Google 導航連結；只有本機單一 Vite 程序容許無 Redis 的 OSRM 示範。

## 3. Vercel 環境變數

在現有 `duck-delivery-map` 專案的 Settings → Environment Variables 填入：

```text
GOOGLE_ROUTES_API_KEY             Routes API 金鑰
GOOGLE_STATIC_MAPS_API_KEY        Maps Static API 金鑰
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
2. Preview 搜尋公開地標，例如清水車站。確認標示 Google Maps、Google 底圖有路線與完整 attribution、5 公里內低消 300 元。
3. 確認 Redis `used` 增加 1；Google Cloud 實際使用紀錄可能延遲，稍後核對 SKU。
4. Preview 將 `GOOGLE_MONTHLY_LIMIT=0` 後重新部署。再查同一地標，確認顯示 OSRM、OpenStreetMap 路線且 Google 帳本不增加。不要為此清零既有帳本。
5. 驗證服務失敗會顯示無法判定及導航連結，不給直線距離結論。恢復設定後才發布正式版。

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
