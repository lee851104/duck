# LINE Messaging API 串接準備

已新增 `app/line_intake.py` 作為獨立的格式轉接器。目前應用程式沒有載入它，沒有新增 Webhook 網址、背景工作、環境變數讀取或資料庫變更。既有 TXT 匯入、AI 轉單、訂單編輯與銷售流程維持原來的入口。

## 已完成

- 使用原始 HTTP bytes 做 HMAC-SHA256 簽章驗證，通過後才解析 JSON，並核對接收帳號。
- 把官方 Messaging API 的 user、group、room 事件轉成 `IncomingEvent`，保留聊天室 ID、使用者 ID、訊息 ID、事件 ID、毫秒時間與重送標記。
- 分開表示文字、圖片、收回訊息；其他事件標示為 `unsupported`，不當成訂單文字。
- 提供 `dedupe_key`，讓未來接收端以 `(destination, event_id)` 建立資料庫唯一約束。同樣內容的新留言有不同事件 ID，不應因內容相同被刪除。
- 文字事件能在呼叫端提供顯示名稱後，以 `to_chat_message()` 轉成現有 `line_chat.Message`；AI 顯示時間採臺灣時間，事件本身仍保留完整 UTC 時間。
- 模組只使用 Python 標準函式庫；明確呼叫文字轉換時才使用既有 `line_chat`。

這是可測試的接收核心，尚非完整接收服務。它不保存已收到的事件，也不會自行去重、下載圖片、處理收回後的訂單或自動送 AI。

## 後續接線方式

```text
LINE Webhook
  → 驗證原始請求與接收帳號（decode_webhook，已備妥）
  → 核對允許接單的聊天室
  → 事件寫入持久化佇列，資料庫原子去重
  → 確認保存成功後回覆 LINE
  → 背景工作取得身分、菜單與必要的前後文
  → 依現有資料表格式建立匯入批次與留言
  → 沿用現有 AI 轉單與訂單管理
```

`decode_webhook(body, signature, channel_secret=..., expected_destination=...)` 回傳事件 tuple；LINE 的 `events=[]` 驗證請求會回傳空 tuple。驗章失敗會拋出 `SignatureError`，格式或帳號不符會拋出 `IntakeError`。多事件請求在全部驗證成功後才回傳，不會產生半批寫入。

正式啟用時仍需完成以下工作：

1. **HTTP 入口與啟用設定**：部署 HTTPS 接收網址、安全讀取憑證、限制請求大小；既有登入與 CSRF 機制只對這個已驗章的入口作適當區隔，不能全域關閉。驗章只證明來自 LINE，仍須限定允許接單的群組。
2. **事件保存與背景工作**：新增獨立事件表／佇列與唯一約束；收到重送時按事件 ID 去重，不能直接略過所有 `is_redelivery=True` 的事件，因為第一次可能尚未收到。處理失敗可重試，並處理事件亂序。
3. **身分與菜單**：Webhook 不直接附帶顯示名稱；缺少 userId 或名稱時需保留待確認狀態。店員以可信任的使用者 ID 設定辨識，不能沿用 TXT 暱稱前綴作身分判斷。菜單與多則連續喊單需要批次／上下文策略。
4. **接上既有批次**：`import_export()` 仍專門處理 TXT 位置比對。API 應另建批次寫入入口，保存來源 ID 對應，讓 `convert_import()` 可沿用；不要偽造 TXT 再走匯入，否則會丟失 API 的身分及去重資訊。`to_chat_message()` 只供 AI 文字格式銜接，並不是完成資料庫串接。
5. **收回與未支援事件**：收回需依目標 messageId 找回原訊息及相關訂單，配合既有銷售紀錄設計人工確認／沖銷流程。圖片尚未下載或辨識；`unsupported` 需記錄及處理，不能靜默遺失或直接轉單。
6. **切換與驗證**：先用測試帳號及隔離資料庫驗證，再明確設定各聊天室採 TXT 或 API。兩種來源重疊的舊留言無法只靠事件 ID 自動對應，正式切換應設定時間界線，避免重複訂單。舊聊天記錄不可假定能由 API 補抓。

目前模組僅按官方 Messaging API 的已公布格式準備，不宣稱支援 OpenChat。若未來 OpenChat 開放不同介面，須新增或調整事件轉接器及接線測試；不能保證只填金鑰即可啟用。

## 離線驗證

在 `inventory_app` 執行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_line_intake tests.test_line_orders tests.test_daily_sales -q
```

新測試涵蓋官方驗章範例、竄改拒絕、多行中文、跨日臺灣時間、重送識別、相同內容的新事件、缺少寄件者、圖片、收回與未知事件。既有接單及銷售測試使用暫存資料庫與假的 AI 回覆，不存取營運資料或呼叫付費 API。

## 規格來源

核對日期：2026-10-03。

- [LINE Webhook 簽章驗證](https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/)
- [LINE 接收訊息、事件重送與去重](https://developers.line.biz/en/docs/messaging-api/receiving-messages/)
- [LINE Messaging API 參考文件](https://developers.line.biz/en/reference/messaging-api/)
