# SDD ledger — plan: D:/duck/docs/superpowers/plans/2026-10-01-customer-shopping.md

2026-10-01. User authorized inline implementation. Spec: D:/duck/docs/superpowers/specs/2026-10-01-customer-shopping-design.md.

Task 1: complete — public product projection, published product flags, source-backed three recipes, authoritative quote expansion, optional condiments, package quantities and source photos. Initial tests failed before shop_catalog existed; final suite green. Missing inventory/price remains unknown; source workbook unchanged.

Task 2: complete — pending orders, client-scoped recovery, private token lookup, persistent rate limit, immutable price snapshots, atomic confirmation/reservation, ready/pickup/cancel/expiry, inventory reservation protection. Customer pickup cannot be directly reversed as a standalone inventory movement. Its regression first failed then passed. Store returns remain a separate inventory operation.

Task 3: complete — responsive customer page, recipe illustrations, product category/search/pagination, adjustable bundles, cart, checkout, private status; separate authenticated order/recipe/product/settings administration. Inventory workbench links added; quantity allocation excludes reservations and indicates them. Mixed cart display order matches server grouping.

Task 4: complete — full unittest command `.venv/Scripts/python.exe -m unittest discover -s tests -q`: 63 tests passed, 26.519 seconds. Browser `tests/browser_shop.cjs` passed on isolated real-data snapshot with eight ingredients given QA-only known stock; desktop 1366×900, phone 390×844, tablet 768×844. Confirmed all three recipes, $260→$150 condiment removal, recipe+single cart $205 correct grouping, lost successful response followed by reload recovery, guest order to admin confirm/ready/pickup, admin recipe edit, source photos, no horizontal page/dialog overflow or JavaScript errors. No physical device verification or native browser text zoom claim.

Final review: fresh read-only reviewer /root/customer_review (gpt-6-astra), no Critical, two Important, one Minor. Single repair/verification pass:

- Fixed lost-response refresh duplicate: browser test reproduced 201 instead of expected existing-order recovery. Client now persists only request identity before submission; on reload or retry, server waits for in-flight submission transaction and recovers by original client identity. Full saved contact payload is unnecessary. Browser recovery passed; unit test proves another client cannot recover it. Closed session/cleared browser storage cannot recover through that client identity; a saved private order link still works.
- Closed transaction evidence gap: independent SQLite connections synchronize with Barrier for confirmation-vs-confirmation and confirmation-vs-walk-in; exactly one succeeds. Added timeout release, persistent rate limit after guest session replacement, replayed pickup request, cross-recipe shared SKU aggregation and immutable price snapshot assertions. All passed. These tests verify existing safeguards, rather than claiming they exposed an oversell bug.
- Added public API 64KB input limit, test first returned 400 instead of 413, then passed.
- Final: minor (deferred): recipe name/ingredient search is not added to the three-card recipe homepage; product search and category filters are available. Revisit recipe search when expanding the menu.

Ruling: No Git repository exists; code stays in inventory_app and no branch/PR/worktree is created. Cost: no Git history until adopted.
Ruling: Existing SQLite app remains the local implementation; Cloud Run/PostgreSQL/HTTPS remain separately planned. Cost: localhost is unavailable to remote customers.
Ruling: Initial accepting-orders setting is false with no pickup slots; real unknown stock remains unchanged. Cost: owner must count stock, confirm dated saleable batches, and set hours before transactions can be enabled.
Ruling: Use committed vector illustrations as recipe artwork and preserve source photos; no extra image-generation dependency. Cost: illustrated dishes are schematic, labeled as such.

Reviewer declined-to-judge outcomes:
- Migration/backup: backup `backups/inventory_2026-10-01_862d10c2.zip` was created before migration, its archive validated, restored to `.qa/shop-restore`, and migrated there successfully. SQLite integrity/FK checks passed, 173 products and 3 recipes verified, 0 customer orders.
- UI: author completed the measured browser cases above, inspected desktop/mobile screenshots; no physical hardware/text-zoom claim.
- Request limit: implemented and verified RED→GREEN.
- Cloud transactions: remain outside local SQLite scope, explicitly documented.

Production verification: before/after SHA256 signatures for products, batches, movements and users identical; SQLite integrity/FKs valid; exactly 3 recipes and 0 real customer orders. Evidence `.qa/production-shop-verification.json`. Main service restarted on port 8765; `/`, `/shop`, public catalog/recipes/session HTTP 200. Original Excel SHA256 values match pre-feature ledger exactly. No production test orders or stock changes. QA browser data/credentials exist only under `.qa`.

Completion: owner can review local customer view at http://127.0.0.1:8765/shop and authenticated management at http://127.0.0.1:8765/shop/manage. Production local service remains running; QA server stopped after validation.
