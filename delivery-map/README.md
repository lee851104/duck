# 菜騎鴨外送範圍教學示範

輸入地址、使用定位或直接在地圖選點，查看是否在菜騎鴨的 3／5 公里外送範圍內。

採單一畫面的查詢工作區：頂部搜尋與定位，地圖填滿剩餘高度；選定位置後才顯示精簡的外送結果與低消。完整須知、店址與資料來源收在原頁面對話框。一般桌面與手機尺寸不需捲動；極矮視窗或放大文字時允許自然捲動，避免裁切操作。地圖支援滾輪縮放，也可用方向鍵移動後按 Enter 選擇中心。

本目錄是獨立的 Vite + Leaflet 靜態網站，可單獨複製或建立另一個 Git 儲存庫。不依賴旁邊的 Flask 庫存系統、資料庫或 Python 環境；不會讀寫店家營運資料，也不提供訂購功能。

## 本機啟動

需要 Node.js 22.12 以上或 24 LTS。

```powershell
cd delivery-map
npm ci
npm run dev
```

開啟 http://127.0.0.1:4174 。

```powershell
npm test
npm run build
npm run preview
```

`dev` 與 `preview` 使用同一個連接埠，請擇一執行。`preview` 提供已建置的 `dist`。

## 部署到 Vercel

正式網址：https://duck-delivery-map.vercel.app/ 。Vercel 專案為 `lee851104s-projects/duck-delivery-map`，目前以本目錄透過 CLI 部署，未連結整份庫存系統儲存庫的自動部署。更新後在本目錄執行 `vercel deploy --prod`。目前上線的是 OpenStreetMap／國土測繪中心版本，尚未啟用 Google Maps 或 Google 用量切換功能。

這是經店家同意的非商業教學範例。先登入自己的 Vercel 帳號，再於本目錄執行：

```powershell
npx vercel login
npx vercel
```

先檢查 Preview 部署，確定後：

```powershell
npx vercel --prod
```

若由 GitHub 匯入整份儲存庫，Vercel 的 **Root Directory 必須設為 `delivery-map`**。若另建僅含本目錄內容的儲存庫，Root Directory 使用根目錄。Framework 選 Vite，Build Command 為 `npm run build`，Output Directory 為 `dist`。已有 `vercel.json`，不需要環境變數、API 金鑰或資料庫。

不要把庫存系統的本機資料、`.env`、備份或帳號資料放到這個目錄。推送本專案時只納入此目錄的原始碼與 lockfile；`dist`、`node_modules`、`.qa`、`.vercel` 已忽略。

## 距離與規則

- 店家座標：`24.2739442, 120.5453111`，依使用者提供的 [Google 地圖店家連結](https://maps.app.goo.gl/ThLryBDRxGa6YcFg6)，於 2026-10-02 確認。店家地址：臺中市清水區中社路 102-21 號。
- 圓圈使用直線球面距離，不是實際行車距離。店家與規則設定在 `src/rules.js`，介面文字在 `index.html` 與 `src/main.js`。
- 距離 ≤ 3,000 公尺：消費滿 100 元免運。
- 3,000 < 距離 ≤ 5,000 公尺：消費滿 300 元免運。
- 範圍內未達低消：20 元／趟。團購商品不計入低消。
- 距離 > 5,000 公尺：不外送，提示來店自取。
- 分類使用未四捨五入距離，顯示值向上取到 0.01 公里，避免 5,001 公尺被顯示成 5.00 公里而引起誤解。
- 一般訂購截止 15:00；台中港重劃區僅免除此時間限制，15:00 後仍不提供蔬果處理。沒有該區可靠邊界資料，因此不自動認定此例外，也不改變距離判斷。
- 16:00 為出發時間，不是保證抵達時間。完整配送／寄放／保冰與社群通知規則可展開查看。
- 定位精度若跨越 3 或 5 公里界線，顯示「請確認位置」，不直接承諾可送或低消。

## 地圖、查詢與限制

- 地圖左上角可切換「街道圖／正射影像」，切換保留位置、縮放與查詢結果。正射影像使用國土測繪中心 [PHOTO2 WMTS](https://maps.nlsc.gov.tw/S09SOA/pro/Wmts_ajax_main.jsp)，圖磚網址為 `https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/GoogleMapsCompatible/{z}/{y}/{x}`，最高縮放層級 19，不需 Google API 金鑰。各區拍攝時間不同，並非即時影像；服務或圖資覆蓋不可用時可切回街道圖。已將圖磚來源加入 Vercel CSP。
- 使用 [Leaflet](https://leafletjs.com/)、[OpenStreetMap 標準底圖](https://operations.osmfoundation.org/policies/tiles/) 與 [Photon 公開示範地理編碼服務](https://github.com/komoot/photon#demo-server)。不使用 Google Maps API，也不會因這個版本產生 Google Maps API 費用。
- Photon 是盡力提供的公開服務，沒有可用性保證；適合低流量教學示範，不適合大量學生同時高頻搜尋。輸入至少 2 個字、停頓 700 毫秒後，使用 Photon 的部分名稱與容錯搜尋列出建議；中文輸入法選字期間不查詢。單一分頁請求至少間隔 1.2 秒，最多快取 30 組結果於記憶體。輸入改變時取消舊查詢、阻擋過期結果；支援上下鍵選取與 Escape 關閉。也可按搜尋鈕完整查詢。
- 開放資料的台灣門牌涵蓋不完整。按搜尋鈕查不到完整門牌時會嘗試同一道路並清楚提示；自動建議不額外發送備援查詢。所有搜尋候選都必須先確認地圖位置。也可直接點圖，或使用定位與地圖中心選點。不能把道路中心點當成精確住宅位置。
- 地址文字會傳送給 Photon。定位座標僅在瀏覽器計算，不做反向地址查詢；地圖供應商仍會收到 IP、來源網址與目前視野的圖磚請求。本站沒有分析追蹤、帳號或資料庫，不記錄地址與定位。
- 定位需要 HTTPS 或 localhost，以及使用者授權。測試時可搜尋公開地標或直接在地圖選點，不必提交真實住址。地圖支援滑鼠滾輪縮放。
- 沒有離線底圖或大量預抓；保留 OSM attribution 與正常 Referer／瀏覽器快取。若使用量增加，須換成有相應額度的圖磚與地址服務。更換服務時也更新 `vercel.json` 的 CSP 白名單。

## 驗證

`npm test` 驗證精確 3／5 公里及剛超界、非法座標、距離公式、定位誤差、顯示值、中文地址分段與外部搜尋結果驗證。

本機已實測公開地標「清水車站」搜尋、選擇候選、確認位置及結果，約 2.68 公里；3 公里內、3 至 5 公里及超過 5 公里的結果已在瀏覽器檢查。真實手機 GPS 精度與權限流程仍須於手機授權後驗證。公開 Vercel 網址需部署後另外確認。
