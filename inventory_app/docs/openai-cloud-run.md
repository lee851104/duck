# 在 Cloud Run 設定 OpenAI 金鑰

正式網站：https://duck-inventory-953640890149.asia-southeast1.run.app/

目前使用 Google Cloud 專案 `duck-inventory`、服務 `duck-inventory`、區域 `asia-southeast1`。金鑰由 Secret Manager 提供給後端，不放在前端、Git、Dockerfile 或一般環境變數明文中。

## 目前設定

| 項目 | 值 |
|---|---|
| OpenAI 金鑰名稱 | `duck_inventory` |
| Secret Manager 名稱 | `duck-openai-api-key` |
| 使用的 Secret 版本 | `1` |
| Cloud Run 環境變數名稱 | `OPENAI_API_KEY` |
| 模型環境變數 | `OPENAI_MODEL=gpt-6-luna` |
| 可讀取此 Secret 的服務帳號 | `duck-runtime@duck-inventory.iam.gserviceaccount.com` |

新金鑰透過 OpenAI Platform 安全建立流程產生，有效期限依建立時選擇為 360 天。另保存在使用者確認的本機 `.qa/cloud-openai.env`，此路徑由 Git 忽略，且不在 Cloud Run 原始碼上傳清單中。不要把整份 env 檔上傳為 Secret 的值；Secret 的內容必須只有金鑰本身。

## 以後自行新增或更換

1. 在 [OpenAI API keys](https://platform.openai.com/api-keys) 建立專用金鑰。金鑰只在安全介面操作，不貼到聊天、截圖或程式碼。
2. 開啟 [Secret Manager](https://console.cloud.google.com/security/secret-manager?project=duck-inventory)。首次設定時按「建立密鑰」，名稱填 `duck-openai-api-key`，密鑰值貼入金鑰本身。若密鑰已存在，點進去按「新增版本」，記下新版本數字，例如 `2`。
3. 在這個密鑰的「權限」頁，確認 `duck-runtime@duck-inventory.iam.gserviceaccount.com` 擁有 **Secret Manager Secret Accessor**。僅授予這一個密鑰的讀取權；目前已設妥，換版本時不必重設。
4. 到 [Cloud Run](https://console.cloud.google.com/run?project=duck-inventory)，選 `duck-inventory` →「編輯及部署新修訂版本」→「變數與密鑰」→「參照密鑰」。環境變數名称填 `OPENAI_API_KEY`，密鑰選 `duck-openai-api-key`，版本選剛新增的數字。目前已有此項，換金鑰時只需改版本。
5. 保留原有資料庫、Google 登入等設定，按「部署」。若手動取消了立即提供流量，需再將流量切到這個新版本。
6. 開啟網站 → **LINE 接單 → 說明 → 測試連線**。出現「OpenAI 連線成功」代表 Cloud Run 能讀到金鑰且可存取所設定模型。此按鈕只查詢模型，不代表已實際轉換訂單或確認足夠推論額度。

金鑰值只有 `sk-...` 本身，不包含 `OPENAI_API_KEY=`。環境變數名稱須完全一致。使用明確版本數字可避免新金鑰尚未驗證就被新啟動的執行個體使用；新增 Secret 版本後仍要更新 Cloud Run 引用並部署。

## 費用與排查

- Cloud Run 的 **US$10 每月上限不包含 OpenAI API 費用**；兩邊分開計費。OpenAI 用量請到 [Usage](https://platform.openai.com/usage) 查看。
- 「尚未設定 OpenAI 金鑰」：確認環境變數名稱與 Secret 版本引用。
- 新版本無法啟動：確認 Secret 版本仍啟用，以及上述服務帳號的讀取權。
- 「金鑰無效或已停用」：新增正確金鑰的 Secret 版本，再部署引用該版本。
- 「額度不足」：檢查 OpenAI API 的付費與 credits；調高 Cloud Run 上限無法解決。
- 更換成功後再停用不用的舊金鑰，並注意回退到舊修訂版本可能仍引用舊 Secret 版本。

維護者使用 `deploy/deploy.ps1` 時，可在 Secret 版本對照 JSON 中提供 `OPENAI_API_KEY: "duck-openai-api-key:1"`。脚本使用 `--update-secrets` 保留其他既有引用，JSON 中不可填入金鑰內容。

參考：[Google Cloud Run 使用密鑰](https://docs.cloud.google.com/run/docs/configuring/services/secrets)、[OpenAI 正式環境金鑰管理](https://developers.openai.com/api/docs/guides/production-best-practices)。
