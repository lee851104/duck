# Cloud Run and Supabase deployment implementation plan

**Goal:** Deploy the existing merchant and guest-ordering Flask app to Cloud Run with durable PostgreSQL data and private Supabase object storage, preserving inventory, accounts, media and transactional behavior.

**Architecture:** Keep the existing SQLite local mode. Explicit cloud mode uses a private PostgreSQL schema and a dedicated runtime database role, plus private object storage for media/exports/backups. Fail closed when cloud configuration is incomplete. Use Cloud Run request billing, zero minimum instances and one maximum instance; no automatic paid upgrades.

**Spec:** `docs/superpowers/specs/2026-10-01-cloud-deployment-design.md`. Scope ruling: preserve the current logical data model and source history for deployment; separate category/supplier dimension-table restructuring is deferred, because changing that model is unnecessary to persist existing business data and would increase migration risk. Google admin/owner/staff roles and guest checkout are now required.

## Constraints

- Existing Google login changes are uncommitted and must be preserved; never reset the working tree or inspect/print secrets. Development files stay in the current authorized workspace. Do not restart the live app during the migration adaptation.
- Keep original SQLite and pictures unchanged until a checked cutover snapshot. Secrets/private exports remain under ignored data/.qa paths, never Docker build context or Git.
- Public routes expose only published products/recipes and token-protected orders. Merchant routes require active authorized Google accounts; only account managers manage allowlists.
- Supabase Free only. No Cloud SQL, VM, VPC connector, paid upgrade, minimum warm instance or unrelated resources. Billing authorization already given; actual billing setup is user-owned.
- Current GCP project: duck-inventory. Billing linked and Supabase Free project created; user completed credential setup and official OAuth callback registration.
- Whole-system public deployment is incomplete until actual PostgreSQL concurrency/restore, remote media, restart durability, OAuth callback and health checks pass.

## Task 1: Durable SQL backend and migration (database worker)

Files: `app/db.py`, `app/postgres.py`, `app/common.py`, `app/products.py`, `app/shop_catalog.py`, `app/shop_orders.py`, `app/inventory.py`, `app/imports.py`, `app/sql/*`, `tools/migrate_postgres.py`, dedicated PostgreSQL tests.

- [ ] Add psycopg PostgreSQL connection implementation with same required connection/cursor/row operations as current SQLite, explicit supported SQL handling and parameter binding.
- [ ] Serialize mutation transactions using one PostgreSQL advisory transaction lock (equivalent to SQLite BEGIN IMMEDIATE for this single store); preserve rollback, optimistic versions, idempotency and reservations. No reliance on one Cloud Run instance for transaction correctness.
- [ ] Put schema in private `duck` schema; idempotent explicit migrations, no automatic cloud schema creation. Separate migrator credentials from runtime CRUD role.
- [ ] SQLite-to-PostgreSQL import into empty destination only, preserve IDs/NULL/text decimal values/foreign keys, reset sequences, verify exact content; do not overwrite live destination. Allow independent QA schema through validated identifiers.
- [ ] Test SQLite compatibility plus opt-in real PostgreSQL CRUD, concurrent counts/order reservation and retry behavior against isolated schema. Tests must not use live local data.

Interface: `connect_db(path_or_dsn, schema='duck')` accepts SQLite Path or postgresql DSN; returned PostgreSQL connection has `dialect='postgres'`. `get_db()` selects `DATABASE_URL` when configured. `init_db(conn)` remains local initializer; explicit PG migration is a separate entry point. Database exceptions integrate with sqlite3.Error compatibility or exported common error classes (tell coordinator).

## Task 2: Durable objects and cloud backups (storage worker)

Files: `app/storage.py`, `app/api.py`, `app/shop_api.py`, `app/backups.py`, `app/invoice.py` if needed, `tools/migrate_media.py`, dedicated storage/backup tests. Coordinate DB files with database worker.

- [ ] Local/remote storage abstraction configured by `STORAGE_BACKEND=local|supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET` (private `duck-private`). Retain same-origin image/download endpoints and their existing authorization; fetch remote objects through backend (no service key or private URL disclosure).
- [ ] Persist media and invoice exports remotely before reporting successful writes; local temp paths may only be temporary computation, never durable references. Unknown upload outcome should permit idempotent content-hash retry.
- [ ] Disable original-files import in cloud mode, with explicit actionable message; migration is performed locally.
- [ ] Remote backup entry point exports a consistent PostgreSQL snapshot plus object manifest; write backup to private storage, seven daily DB snapshots; do not delete images needed by backups. CLI/Cloud Run job rather than daemon in request-billed server.
- [ ] Tests for remote missing/failure, upload then retrieval from fresh client, public/private media authorization, persistent export and backup integrity. Migrate existing 348 media objects (146.47 MiB) with manifest/hash validation and idempotent resume.

Interface: coordinator sets `CLOUD_MODE=True`, `DATABASE_URL`, `DATABASE_SCHEMA='duck'`, `STORAGE_BACKEND='supabase'`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET`; agent documents storage helpers and backup job invocation.

## Task 3: Cloud bootstrap, build and release (coordinator)

Files: `app/__init__.py`, `cloud.py`, `Dockerfile`, `.dockerignore`, `.gcloudignore`, `requirements.txt`, `deploy/*`, cloud startup tests and docs.

- [ ] Strict environment-only cloud setup: require external DB/object storage, stable SECRET_KEY, HTTPS Google callback and admin Email. Never read local credential files or initialize cloud schema automatically.
- [ ] Run Waitress on 0.0.0.0:$PORT, no in-process scheduled worker; proxy trust restricted to Cloud Run topology. Cloud-safe store/source limits and upload ceilings.
- [ ] Build context allowlist excludes actual inventory, Excel, credentials, backups, QA outputs and virtualenv; ship only app + requirements + cloud entry point. Health probe verifies DB connectivity without leaking internals.
- [ ] Prepare gcloud deploy and secret setup using files/stdin (no secret output or CLI literal). Use source build, minimal service accounts, HTTPS run.app address, constrained instances/CPU/memory/concurrency and explicit region. Configure real budget/spend cap where supported; do not call max instances a spending hard cap.
- [ ] Obtain GCP CLI login and Supabase project details safely, link billing, create private buckets/schema/runtime role, migrate snapshot and objects, verify before traffic cutover.
- [ ] Register HTTPS OAuth callback in existing client; user may need to do that in Google Console. Deploy and test guest pages, merchant auth, real durable reads/writes, concurrency, backups/restoration and second revision/restart. Preserve rollback snapshot and designate cloud as single writer.

## Review focus

- Boot with one missing cloud secret must refuse startup instead of silently falling back to a blank SQLite database.
- Two concurrent requests must not oversell or double-apply a retry; PostgreSQL validation uses separate connections.
- A fresh container must retrieve previously saved photos/exports and validate existing sessions using stable secrets.
- Guest media URLs and tokens must not grant access to unpublished photos, admin lists or another order.
- A interrupted migration or upload must be resumable without overwriting a non-empty production database or promoting partially copied data.

## Progress ledger

- Planning/context read complete; user supplied GCP project and confirmed missing billing link/Supabase project. Waiting on billing setup; independent implementation can proceed.
- User selected Cloud Run auto-pause threshold US$1/month, explicitly accepting small costs and reporting-latency overage. This is a trigger threshold, not a guaranteed total bill ceiling; other GCP service costs must remain visible and constrained. Do not automatically lift an enforced cap.
- Database and object-storage implementation delegated in parallel on disjoint files. Coordinator owns bootstrap, cloud packaging and user setup guidance.
- Cloud code, migration/storage tools, container allowlists and source deployment script prepared. Latest combined suite: 128 tests, 122 passed / 6 real PostgreSQL tests skipped (before final grant/proxy adjustments). Cloud bootstrap targeted 5 passed after nearest-proxy IP fix. Reviewer found runtime pg_dump unable to read schema_migrations; fixed with SELECT-only grant; actual service validation still pending.
- Google CLI 587.0.0 installed under ignored .qa/cloud-tools with official SHA256 verification; gcloud auth login succeeded as lee851104@gmail.com. Project duck-inventory ACTIVE, number 953640890149, billingEnabled=true. CLI config remains ignored .qa/gcloud-config.
- User created Supabase project jclgcdwqodblvmwkddau. Session pooler host aws-0-ap-southeast-1.pooler.supabase.com:5432, postgres.<project-ref>, postgres database. Password is being entered by user into local masked console; only private .qa/cloud-private/database.json will hold DSN. Do not print or read secrets into tool output.
- User screenshot shows a new monthly Cloud Run spend cap (50/80/100 notifications). User subsequently confirmed its actual currency USD and amount 1. Billing API v1 only returned a separate older TWD 5 alerts-only budget; it cannot establish the spend cap currency. Do not lift/increase cap automatically.
- Source upload allowlist verified via gcloud meta list-files-for-upload: only code/static/templates/sql/tools and Docker entrypoint files, no production data/credentials/workbooks/QA/venv.
- Final cutover: local writer stopped; all business rows matched exactly in private duck schema and all 348 media objects (153,582,597 bytes) verified. Dedicated runtime DB role and Secret Manager references active. 135 local tests passed; all six real PG tests passed over initial run and targeted role-membership test repair. Synthetic PG dump/restore compared 22 tables/20 rows and sequences exactly in isolated QA schema.
- Published revision duck-inventory-00002-6bw with min0/max1, 512Mi, concurrency4, timeout60, request CPU billing. Public health/shop/catalog/recipes/photo hashes and anonymous-admin denial passed. Nine merchant endpoints tested against migrated cloud DB. OAuth HTTPS redirect passed and user confirmed Console registration; actual Google account round trip awaits user.
- Dedicated backup Job duck-backup uses final image, one task/no retry/15m, two scoped Secrets and web identity's job-scoped execution permission. First execution duck-backup-mlvcr succeeded; cloud archive hash, dump and all 348 manifest entries verified against cutover originals. No daily schedule: full media verification daily would consume ~4.3GiB/month.
- Remaining acceptance limits: real provider application-level proxy IP spoof probe not performed (nearest-hop unit test passed); full production-data restore rehearsal not performed (isolated synthetic restore passed). Guest ordering stays disabled until store sets pickup slots and verifies sellable stock. Public availability verified; awaiting user's cloud Google login.
