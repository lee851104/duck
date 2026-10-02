# 菜騎鴨

單店商品、庫存與每日銷售管理系統，使用 Python、Flask 與 SQLite。

- 店家：庫存進出貨、盤點、批次效期、圖像價目表、商品對應、發票商品檔匯出與備份。
- 每日結帳：將當天賣出的商品填成一張銷售單，預覽確認後統一扣庫存，可查詢與整張沖銷。
- 商品依原分類排列，同分類照片優先；缺圖使用菜騎鴨預設圖。
- 系統記錄後自動同步本機庫存、價目及發票三份 Excel；匯出頁只提供庫存管理表下載。

## 啟動

需要 Python 3.12。於 PowerShell 執行：

```powershell
cd inventory_app
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

瀏覽器開啟 `http://127.0.0.1:8765`。首次使用需建立管理密碼；「每日銷售單」位於 `/#daily-sales`。客人下單已停用。

詳細操作、資料匯入與備份方式請見 [使用說明](inventory_app/README.md)。

## 資料

此倉庫保存程式、測試、設計文件與品牌素材。原始 Excel、商品照片資料庫、帳號、營運資料、金鑰及備份不提交至 Git；從 GitHub 下載後需自行匯入資料。將三份原始 Excel 放在根目錄的 `raw_data` 資料夾，再依使用說明匯入。老闆確認回覆 JSON 也放在此處；原始檔與回覆不加入 Git。舊的 `原始資料` 資料夾仍可相容。

目前為本機版本，推送 GitHub 不會自動部署網站。

## 測試

```powershell
cd inventory_app
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

瀏覽器驗證腳本在 `inventory_app/tests/browser_*.cjs`；其瀏覽器及 Playwright 路徑為開發機設定，其他環境需調整。
