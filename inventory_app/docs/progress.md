# SDD ledger — plan: D:/duck/docs/superpowers/plans/2026-10-01-inventory-system.md

2026-10-01 UI/UX follow-up: user explicitly permits scrolling and paging within the single-page app. Supersedes original viewport-fit row reduction. Fixed navigation with scrollable main; 10 inventory/history rows; catalogue 12/24/48 cards, contain-fit photos, lazy loading, present/missing filters with counts, and keyboard-accessible photo/detail dialogs. Neutral missing-photo labels preserve absent source data. Receive green, issue blue, count amber; danger red, text labels and visible focus. Unit/API regression first failed at old 10-row catalogue cap then passed. Suite 49/49 (17.094s). Browser gallery desktop/mobile/tablet passed (1366×768,390×844,768×700); desktop/mobile four-view and receive/count/issue workflow checks passed, no JS errors/horizontal overflow. 200% dialog text validation and submit passed. Source photo/card associations not re-guessed. No real inventory transactions during UI verification; isolated QA databases only.

2026-10-01 source-data follow-up: user explicitly authorized real Excel normalization/import and selected inventory workbook as price authority. Imported 173 products / 176 batches, all 186 catalog cards / 96 invoice rows. 56 catalog links, 14 invoice links, 9 fixed vegetable price tiers; 130 catalog and 73 invoice mappings remain unresolved due missing/contradictory identity or packaging. Full source/collision/price audit is under data/normalization; original Excel hashes unchanged. Before/after backups created. Every imported batch reconciled for quantity, cost and dates; SQLite FK/integrity and authenticated read-only API checks passed. See docs/data-normalization.md.

Same follow-up: source comparison demonstrated invoice codes are a separate namespace. Export tests first failed for preserving external identifiers; fixed one line to retain invoice_items.code while linking current name/price. Final suite 48/48 passed (13.480 seconds). No UI layout change. Cloud Run + Supabase chosen by user with free-tier preference and billing acceptance; design saved at D:/duck/docs/superpowers/specs/2026-10-01-cloud-deployment-design.md. PostgreSQL/storage adaptation and cloud deployment have NOT been implemented; no external projects created or credentials obtained.

Spec: D:/duck/docs/superpowers/specs/2026-10-01-inventory-design.md

Execution: inline, authorized 2026-10-01. Tasks 1–8 complete.

Current state: all eight tasks implemented; final suite 47/47 green, four browser acceptance scripts green, local startup HTTP 200. Verification details: docs/verification.md.

Task 1: complete — five app/auth tests passed after initial missing-app RED. Source code only; UI and startup remain later tasks.
Task 2: complete — thirteen inventory tests passed, whole suite 18/18 at this stage. First run found an unrequested restriction on recording expired receipts. Removed it: expired physical stock must remain recordable; sales still reject it.
Task 3: import preview/commit tests passed (4); original files yielded 176 rows, 186 cards, 96 invoice items and 169 card images. A source fractional-cost regression was then added RED→GREEN to preserve formula results rounded to six decimals.
Tasks 4/5/6/7: implementations present, API tests 7/7 and export/backup tests 9/9 passed. Browser and integrated acceptance pending.
Ruling: Commands use validated dictionaries rather than separate dataclasses because the API and forms already share this shape; common validators provide type/number checks. Cost: less static typing, covered at runtime by mutation tests.
Ruling: Cache source monetary values to six decimal places on import; original Excel formulas include recurring fractions. Retain original files for full precision. Cost: sub-micro-unit rounding; prevents valid costs being lost as missing values.
Ruling: Co-locate UI views into app.js (overview/inventory/catalog/history), operations.js and data.js instead of one module per page; shared rendering is small and coupled. Cost: larger primary JS file, no behavioral change.

Final review: fresh read-only reviewer /root/final_review (gpt-6-astra), 41 tests green at review time. Four Important findings, no Critical. One repair pass:
- New products omitted when source cards existed: regression test RED→GREEN; unmatched products now get generated catalog entries.
- Unknown stock not shown on catalog/print: browser_review.cjs RED→GREEN; explicit 未盤點 label in both outputs.
- Invoice pending state/details hidden: browser_review.cjs RED→GREEN; status and paged issue list now visible.
- Non-collision import issues hidden: unit + browser regression RED→GREEN; every issue retained/displayed with source and original value, acknowledgement required before preserving unknown inputs.
Final: Ruling: Reviewer classified category filtering and history product/batch lookup as Minor; regraded Important because these are core operator lookup functions. Both fixed in the same pass. Cost: two extra UI controls, covered by API/browser regressions.
Final: Ruling: Browser resize at 390×450 tests form access with reduced space, not a physical phone keyboard. Normal 390×844 and 1366×768 views verified. Physical mobile hardware remains unverified; cost: device-specific behavior may differ.
Final: Ruling: Original media files are preserved and extracted by drawing anchors; no exhaustive visual verification of every photo/card pair. User confirms card/product mappings. Cost: some source image/card placements may need adjustment.
Final: Ruling: Backup restore/invalid paths/missing-source failures tested, not physical disk exhaustion or power loss. Atomic archive rename avoids promoting partial files. Cost: OS/hardware fault behavior not fully simulated.
Additional residual checks in same repair pass: backup retry button had an expired event.currentTarget after await; browser failure test RED→GREEN. Expected issue total now must match batch allocations; atomic rollback regression RED→GREEN.
Ruling: Added an explicit 'new invoice item' form for newly created products; category/tax must be supplied by the operator, never guessed. Cost: one optional setup step; duplicate additions are idempotent and tested RED→GREEN.
Deferred minors: none after regrading the two functional lookup findings.

Task 3: complete — real source preview and seven import tests, including explicit unknown acknowledgement and source-value preservation.
Task 4: complete — 8/8 responsive view combinations no root scrolling/clipping; read failure shows retry.
Task 5: complete — actual browser receipt/count/issue flows; saved quantity, missing expiry validation, preserved inputs; service quantities and retries covered.
Task 6: complete — new/existing catalog and invoice items, seven-column values-only XLSX, preserved identifiers/tax, pending export and issue details, print unknown state tested.
Task 7: complete — backup/restore tests green, daily worker installed, startup script produced healthy service.
Task 8: complete — final unittest suite 47/47 (17.067 seconds), browser_check/extended/review all exit 0, independent reviewer findings addressed by RED→GREEN regressions. Real 200% font settings/physical mobile hardware and all source images not exhaustively visually verified, explicitly noted in verification.md.
Final: no Git integration step applies. Preserve code, docs and original source files in place; no branch/PR created, no source Excel edits, no cloud deployment.
Additional final accessibility verification: browser_font.cjs doubled computed dialog font sizes at 390×844; validation and successful submit remained usable. This supplements the earlier small-viewport keyboard-space simulation; physical devices/native browser zoom remain outside measured coverage.

Ruling: No Git repository exists; use the approved separate inventory_app folder and retain this ledger instead of Git-dependent workspace scripts. Original Excel files remain read-only. Cost: no Git commit history until the user adopts Git.

Pre-flight: Tasks 1→2 database/command interfaces; 2→4/5 query and mutation interfaces; 3→5 import preview/resolution; 2→6 price revisions; 1→7 backup snapshot. No contradictory interfaces found.

Source SHA256:
- 庫存: 103EA3B1A568BF142B6B9D57F61CBF93C300C3447673AF0BFB958EC2B58A9531
- 價目: 08A92110275956422B3E29DD5F3A5F44F6B608D9C5BA3F2DBF550885080534D5
- 發票: A3FB7B3DDE07B8D99C5404A1BDEBA06C79CA14A456DF619D4BA6056F01E733A3

2026-10-01 customer shopping: implemented /shop and /shop/manage, 173 published source products, 3 source-backed recipes, optional condiments, guest pickup orders, atomic reservations and inventory safeguards. 63/63 unit/API tests; isolated browser journey and recovery-after-lost-response passed at desktop/mobile/tablet sizes. Real DB migrated after verified backup/restore; product/batch/movement/account hashes unchanged, zero real orders, accepting orders disabled. Detailed ledger: docs/customer-shopping-progress.md.

2026-10-01 photo follow-up: visually reviewed 60 candidates and all 55 existing product photos. Applied 58 photo-only links, held back two milk images with 24-pack labels; 113 total photos, 60 missing/unconfirmed. Fixed original Excel overlay selection from backmost to frontmost (regression RED→GREEN); corrected 3 source cards and rock-sugar product image. Added recipe ingredient thumbnails with missing-photo fallback. 64/64 tests passed (31.660s); production read-only browser verified all 113 image URLs decode, recipe image counts 2/2/3, desktop/mobile no dialog overflow, no JS errors. Before/after DB comparison confirmed price/stock/units/specifications/order/account/catalog SKU mappings unchanged; photo audit movements recorded.

2026-10-01 touch stocktaking follow-up: user reports existing stocktaking is hard to tap and understand. Bounded change to existing bulk-count flow: merchant homepage defaults to stocktaking, photo cards replace the horizontally scrolling table, independent expiry batch rows retained. Added >=54px +/- controls, explicit same/zero/clear-one actions, physical stock/reservation explanations, difference feedback, page draft progress, and sticky explicit save. Unknown quantities remain blank, never silently become zero. Mobile explanatory header reduced so controls appear earlier. Existing backend, data schema and real inventory unchanged.
Verification: tests/browser_stocktake_touch.cjs RED (no card) -> GREEN, desktop1366/mobile390, known/unknown/decimal/zero values, expiry separation, clear-one, conflict recovery preserving other drafts and fresh expected_version, large touch targets and no sideways overflow. tests/browser_merchant.cjs passed isolated .qa/merchant-data actual save/retry, navigation/paging/resize preservation; browser_merchant_race.cjs and browser_merchant_limit.cjs passed stale GET and 200-draft cap. Full unittest suite 74/74 passed (62.517s).
Review per requesting-code-review: /root/stocktake_touch_review read-only, no Critical/Important, one minor recovery edge reproduced and fixed: editing another row cleared errorBatch while recovery button remained; regression first timed out, then passed after preserving conflict identity until recovery or explicit clearing of that row. Final touch and race browser tests passed after repair. Reviewer also checked reduced-height mobile viewport. No deferred findings. Static assets are served live; no production database changes or stocktaking writes were performed. README updated; QA server stopped after acceptance.
# 2026-10-02 Google 店家帳號與顧客免登入

- 增加 Google OIDC 登入、指定系統管理員首次綁定、老闆與員工 Email 授權清單與停用／重新啟用。Google 模式停用原密碼入口，每次請求檢查帳號狀態，停用即撤銷工作階段。管理員能管理老闆與員工，老闆僅管理員工。
- 帳號管理放在老闆的設定內，顧客有獨立免登入選購入口；既有下單姓名、電話、取貨日期和時段持續必填。
- 新增獨立 Authlib 驗證測試，包括本地 RSA 簽章、錯誤 state／nonce／issuer／audience、偽造簽章、逾期、工作階段撤銷與 CSRF；完整 Python 測試 88 項及隨後新增的本機設定測試 1 項通過。三級角色與登入失效恢復的瀏覽器測試、既有盤點回歸測試通過；獨立程式審查無待修項目。
- 桌機 1366px、手機 390px 登入及帳號操作瀏覽器測試通過，截圖放在忽略的 `.qa`。OAuth 設定步驟在 `google-login.md`。
- 使用者已提供系統管理員 Email，存入忽略的本機 `data/auth-config.json`；老闆信箱可之後在後台新增。尚未建立 Google OAuth 用戶端，因此沒有切換現行服務至 Google 模式，也尚未完成真實 Google 帳號端到端登入驗證。現有商品、照片與訂單未修改。
- 已先以 SQLite backup 建立本機資料庫快照，再重新啟動 8765 服務載入程式。公開 session 驗證仍為 password 模式、Google 尚未就緒、原帳號仍存在。
# 2026-10-02 OAuth 本機啟用

- 使用者已建立 Google Cloud 專案、同意畫面及測試帳號，並下載網頁應用程式 OAuth JSON 到忽略的 `data/`。
- 已核对下載憑證的型別與回呼網址，將設定以原子替換寫入忽略的 `data/auth-config.json`，保留先前設定副本；未顯示憑證內容。現行服務已切換至 Google 模式並重新啟動。
- 14 項登入測試通過。實際 HTTP 檢查確認 Google 登入入口成功導向 accounts.google.com、callback 正確、有 state／nonce／PKCE；顧客頁面與商品 API 仍公開、店家 API 仍要求登入。
- 使用者本人尚待完成 Google 選帳號與回站步驟；尚未宣稱完整真實登入成功。既有庫存與訂單未修改。

# 2026-10-02 Cloud Run 正式部署

- 本機 Google 登入後已有管理員帳號；雲端搬移保留帳號、權限、session key 及所有商品資料。本機 8765 服務已停止，後續正式資料以雲端為準。
- 已部署公開 Cloud Run HTTPS 網站，使用 Supabase Free PostgreSQL/private Storage。173 商品、176 批次、433 異動、3 道料理逐筆比對，348 照片物件全部 hash 驗證。
- 第二版網站、匿名權限、照片、Google 正式回呼導向驗證成功；使用者已於 Console 儲存回呼，完整雲端登入等待本人確認。
- 雲端備份採手動啟動獨立 Cloud Run Job；首次備份成功且 manifest/dump 驗證完成。已做隔離合成資料的 PostgreSQL 還原測試，不曾覆寫正式庫存。
- 保留尚未開放接單設定。完整資源、費用門檻與驗收範圍見 `cloud-deployment.md`。
