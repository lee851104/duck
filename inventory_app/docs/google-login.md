# Google 店家登入與帳號管理

## 使用方式與權限

- 顧客 `/shop` 不需要登入。送單必填取貨姓名、聯絡電話、取貨日期與時段；不建立顧客帳號，不要求 Email、地址或生日。
- 系統管理員以指定的 Google 帳號首次登入，自動建立管理員權限。只信任設定的 Email，其他先登入的人不會成為管理員。
- 系統管理員從「設定 → 管理登入帳號」新增老闆或員工 Email；老闆只能新增及管理員工。可停用及重新啟用有權管理的帳號。新增是授權清單，不會寄邀請信。
- 員工可管理商品、盤點、處理訂單與原有店務設定；不能管理登入帳號。第一版沒有更細的功能權限、既有帳號角色變更或系統管理員轉移介面。
- 停用會讓現有工作階段失效，重新啟用後仍須重新登入。系統管理員不能在介面停用；老闆也不能停用自己或其他老闆。
- 請使用 Gmail 或 Google Workspace 帳號。以第三方私人信箱註冊的 Google 帳號不開放首次綁定，避免用不受 Google 管理的 Email 取得店家權限。

## Google Cloud 設定

1. 在 Google Cloud 的 Google Auth Platform 建立或選擇專案，填寫應用程式名稱與聯絡資料。
2. 依使用帳號設定對象；一般 Gmail 使用外部對象。測試期間將管理員、老闆及員工加入 Google 測試使用者；正式服務前依 Google 畫面完成發布設定。
3. 建立 OAuth 用戶端，類型選「網頁應用程式」。只要求 `openid email profile`，不要求雲端硬碟等額外權限。
4. 加入授權重新導向 URI：本機是 `http://127.0.0.1:8765/auth/google/callback`；正式站是 `https://你的網域/auth/google/callback`。必須和環境變數完全一致，包含協定、連接埠與路徑。
5. 把 Client ID、Client Secret 放在執行網站的環境變數。正式 Cloud Run 使用 Secret Manager 注入 Secret；不要放進 Git、前端或對話。

本機 PowerShell 在啟動程式的同一視窗設定（佔位文字要自行替換）：

```powershell
$env:AUTH_MODE = 'google'
$env:GOOGLE_CLIENT_ID = '你的用戶端ID.apps.googleusercontent.com'
$env:GOOGLE_REDIRECT_URI = 'http://127.0.0.1:8765/auth/google/callback'
$env:GOOGLE_ADMIN_EMAIL = '系統管理員的GoogleEmail'
$googleSecret = Read-Host 'Google Client Secret' -AsSecureString
$env:GOOGLE_CLIENT_SECRET = [System.Net.NetworkCredential]::new('', $googleSecret).Password
.venv\Scripts\python.exe run.py
```

請先結束舊服務，再從專案的 `inventory_app` 目錄啟動。不同 PowerShell 視窗不會自動繼承上述設定。程式也可讀取資料目錄的 `auth-config.json` 持久設定（整個 `data/` 已排除 Git），但不會自動讀 `.env`。程式傳入設定及環境變數優先於 JSON。

此本機的系統管理員 Email、callback 與已下載的 OAuth 憑證已存入忽略的 `data/auth-config.json`，現已啟用 `AUTH_MODE=google` 並重新啟動。其他環境需填入 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、管理員 Email 與 callback，再啟用 Google 模式。正式部署應用環境變數及秘密管理服務，不上傳這個私人檔案。OAuth 用戶端類型需選網頁應用程式，憑證不可貼在公開對話中。

## 資料與安全邊界

- Google 只處理登入身分；庫存、訂單仍在原有資料庫。`staff_accounts` 保存授權 Email、Google `sub` 識別碼、姓名、角色、狀態、版本和最後登入時間；`account_events` 保存新增與停啟用紀錄。
- 登入採 Authlib 的伺服器端 OpenID Connect 授權碼流程與 PKCE，驗證 state、nonce、簽章、issuer、audience、有效期。Email 首次綁定後以穩定的 Google `sub` 識別，不會用另一個同 Email 帳號覆蓋。
- Cookie 不保存 Google access token 或 ID token。店家工作階段最長 8 小時；每次請求都重新檢查帳號狀態與版本。
- Google 回站採頂層 GET，因此 Google 模式設 `SameSite=Lax`，API 寫入仍強制 CSRF。正式 HTTPS callback 會自動設 `Secure` cookie；`HttpOnly` 維持開啟。
- `AUTH_MODE=google` 後，舊共用密碼、首次密碼設定及舊密碼工作階段全部停用。Google 設定缺漏時不自動降回密碼登入。工作階段失效會回到登入入口，登出可安全重複執行且仍需要 CSRF。
- 未設定 `AUTH_MODE` 的既有本機環境維持密碼登入，避免 OAuth 尚未配置就無法進入現有店務。正式部署應明確設 `AUTH_MODE=google`。
- 既有密碼資料保留以便本機回復，原本庫存、商品照片和訂單不做刪除或重建。雲端資料庫、共享 Cookie 簽章金鑰和檔案儲存仍需在部署階段接好，本次沒有部署雲端。

## 驗證

`tests/test_google_auth.py` 使用隔離資料庫，測試授權、停用撤銷、CSRF、舊密碼封鎖、錯誤 state，以及本地 RSA 簽章的有效／偽造／逾期／錯誤 audience、issuer、nonce。供應者的網路交換以測試資料替代，不會登入真實 Google 帳號。

`tests/test_shop.py` 驗證 Google 模式下顧客仍免登入送單，但缺少聯絡或取貨資訊時會拒絕。`tests/browser_accounts.cjs` 驗證桌機、手機登入入口、帳號操作、員工介面與未設定狀態。

實際 Google 帳號登入需要部署者建立 OAuth 用戶端後另外驗證。修改 `GOOGLE_ADMIN_EMAIL` 不會自動轉移已建立的系統管理員；它只用於首次綁定。

參考：[Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)、[Authlib Flask 整合](https://docs.authlib.org/en/latest/oauth2/client/web/flask.html)。
