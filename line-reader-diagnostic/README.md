# LINE 唯讀文字診斷 v2.1

**新增聊天匯出監看測試版：**`Start-Export.cmd`，詳見 [匯出監看-使用說明.md](匯出監看-使用說明.md)。這版會在你啟動並校準後操作 LINE 選單及儲存視窗，將完整文字匯出與舊基準比對，只輸出新增記錄。原有唯讀診斷行為不變；即時 LINE 操作仍待使用者驗證。

**新增一般留言 OCR 測試工具：**雙擊 `Start-OCR.cmd`，使用方式見 [OCR-使用說明.md](OCR-使用說明.md)。它會由你啟動後擷取框選畫面，與本頁不截圖的 UIA／MSAA 診斷不同。既有截圖 OCR 已測試；即時 LINE 監看仍待使用者驗證。

由你啟動的 Windows 小工具，檢查電腦版 LINE 是否透過 UI Automation 或 MSAA 提供文字。這版只取得一次介面快照，不自動監控、不辨識訂單。

v1 的實際報告只有社群標題，108 個元件未取得留言。v2 會檢查 Group／ListItem／Custom 等元件的文字模式、列出支援模式、擷取 HelpText／ItemStatus，並另外讀取同一視窗的 MSAA client 樹。兩套介面分開保存，不將介面掃描完成當成訊息讀取成功。

v2 的 2026-10-03 09:15 實測讀到 92 個 UIA 元件和 99 個 MSAA 元件，仍沒有子元件文字。MSAA 的 96 個 `Description: HRESULT 0x80020003` 表示不提供選用描述欄位，v2 誤將它們計入部分讀取失敗；v2.1 改記為 `UnavailableFields`，保留證據但不製造失敗訊息。v2.1 另記錄 ValuePattern 的 `IsReadOnly` 和略過原因，對 `LcText`／Text／ListItem 補讀 Value getter，避免供應端的可寫旗標讓文字直接被略過。這些修正尚不能證明 LINE 正文已可讀。

## 使用

1. 在電腦版 LINE 自行打開菜騎鴨社群，建議使用獨立聊天室視窗，並自行展開要測試的討論串。
2. 雙擊 `Start.cmd`，或直接執行已編譯的 `bin\LineReaderDiagnostic-v2.1.exe`。確認標題有「v2.1 — UIA + MSAA」。啟動檔會使用 Windows 內建的 .NET Framework 編譯器建立小工具，不下載套件。重新編譯前請關閉舊的 v2.1 診斷視窗；無須關閉 LINE。
3. 點「重新整理 LINE 視窗」，從完整標題選擇目標。程式不會自動挑選同名或其他聊天室。
4. 點「讀取選定視窗」。UIA 階段最多 40 秒，MSAA 階段最多 25 秒，通常會提前完成。讀取期間保持 LINE 的社群、討論串和捲動位置不變。即使 UIA 失敗，仍會在重新確認目標後嘗試 MSAA；MSAA 失敗不會丟棄已保存的 UIA 結果。
5. 在工具內查看「文字結果」、兩種介面的有文字子元件數及原文，或點「開啟報告資料夾」。每次讀取會產生一份 UTF-8 `.txt` 與 `.json`，檔名以 `read-v2.1-` 開頭，保存在本資料夾的 `data`，已排除 Git 追蹤。

程式不會切換焦點、點擊、鍵盤輸入、捲動、操作剪貼簿、截圖、連網、使用 OpenAI API，也不會存取庫存系統。啟動／切換到診斷工具本身仍是一般 Windows 視窗操作；LINE 的已讀行為取決於你自行開啟聊天室的操作。

目前改用 C#／.NET 直接呼叫 Windows UI Automation，免安裝 Python、pywinauto 或額外執行環境。需要 Windows 桌面及 .NET Framework 4.x；無需系統管理員權限。不要為了讀不到而提升權限，先確認 LINE 與小工具是否都以一般使用者執行。

## 如何判斷結果

- 看得到商品、數量原文：表示這個畫面至少提供部分可讀文字；還要核對作者、時間和訊息邊界。
- 只有視窗標題、按鈕名稱：這次 UIA 快照尚未取得聊天正文，不能當作讀取成功。
- `snapshot_ready`：在限制內完成允許讀取的介面樹快照，不代表整串訊息完整。
- `partial`：部分元件失敗或達到時間、深度、字數、數量上限；不可當作完整資料。
- `minimized`：請自行還原 LINE，再重試。
- `failed`／`timeout`：讀取失敗，不能解釋為「沒有新訊息」。外部逾時會終止本工具的讀取子程序，不會終止 LINE。

UIA 提供的是介面元件，沒有保證一個元件就是一則訊息。原始 JSON 保留父子關係、元件類型、Name、TextPattern、Value、支援模式、HelpText、ItemStatus、offscreen、截短和錯誤標記；不依文字內容去重、不猜作者、不把 UIA 識別值當成 LINE 訊息 ID。密碼、Edit 及 LINE MessageInputPanel 子樹略過。除整個 Window 外，其他元件都可探查 TextPattern；只有 range 明確標示唯讀時才讀取內容，遇到可編輯、混合或未知狀態則記錄原因並略過。ValuePattern 保留 IsReadOnly 及讀取策略：一般容器只讀唯讀值，文字標籤與列表項目允許讀 getter；所有路徑都不執行 setter。

MSAA 透過 `AccessibleObjectFromWindow(OBJID_CLIENT)` 與 `AccessibleChildren` 取得同一視窗的子元件。先檢查 role/state，略過輸入欄、密碼或無法確認狀態的子樹，再擷取 Name／Description；Value 限唯讀、靜態文字及列表項目。只讀屬性，不使用預設動作、選取或寫入。MSAA 元件索引與 UIA 分開，不是 LINE 訊息 ID。

兩種介面由 LINE 決定暴露哪些資料；應用程式可能用自訂元件表示輸入內容，因此報告仍應視為含有可見介面資料。有文字可能只是按鈕或標籤，不能據此宣稱已收到訂單。

程式只讀取選定 LINE 視窗的元件樹；每輪核對 HWND、程序 ID、程序啟動時間與完整標題。這能避免目標被關閉或更換，但同一個標題內切換討論串未必可偵測，所以測試期間請不要操作該聊天室。

## 第一輪實際核對

自行準備同一個串文的兩個畫面，各讀一次：

1. 串文第一段：核對 5～10 則留言的文字、作者、時間。
2. 自行捲動到下一段：核對是否讀到新的留言，觀察報告是否仍包含上一段。
3. 回到第一段再讀一次：確認同一畫面的文字是否一致。

若要交回分析，優先提供診斷 `.txt`；可先遮去不必要的個人資訊。程式不會自動上傳報告。此工具不會替你補載未顯示的留言，所以不能用它證明完整收單。

## 驗證範圍

開發時可執行 `bin\LineReaderDiagnostic-v2.1.exe --self-test <輸出 JSON 完整路徑>`。22 項離線檢查包含目標身分比對、略過輸入／密碼元件、唯讀 range 防護、文字標籤 Value getter、選用描述不支援與真正存取錯誤的分類、文字截短、Unicode／換行保留、重複元件保留、報告完整性標示及參數引用；不列舉或讀取 LINE。

`--msaa-fixture-test <輸出 JSON 完整路徑>` 只建立程式自己擁有的隱藏模擬控制項，驗證 MSAA 呼叫能讀出「測試商品＋1」，並正確識別應略過的輸入欄。這不是 LINE 實測。

實際 LINE 的元件相容性、串文完整性及畫面操作仍須由使用者啟動上述測試後核對。工具權限阻擋不等於 LINE 本身不提供 UIA 文字。

技術參考：[Microsoft UI Automation](https://learn.microsoft.com/en-us/dotnet/api/system.windows.automation.automationelement.findfirst)、[TextPattern](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/ui-automation-textpattern-overview)、[MSAA AccessibleObjectFromWindow](https://learn.microsoft.com/en-us/windows/win32/api/oleacc/nf-oleacc-accessibleobjectfromwindow)、[AccessibleChildren](https://learn.microsoft.com/en-us/windows/win32/api/oleacc/nf-oleacc-accessiblechildren)。
