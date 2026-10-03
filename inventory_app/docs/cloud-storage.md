# Private cloud objects and backups

Local mode keeps existing `data/media`, `data/exports` and SQLite backup behavior.
Cloud mode requires `STORAGE_BACKEND=supabase`, `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, and private `SUPABASE_BUCKET` (default `duck-private`).
The storage client checks that the bucket is private before accessing objects.
Browser URLs remain `/media/...`, `/shop/media/...` and authenticated invoice
download routes. Service keys and direct private storage URLs never reach clients.
Storage failures return 503 and never fall back to container files.

`app.storage.get_storage()` provides immutable `put(key, bytes)`, `read(key)` and
`exists(key)` methods. Remote storage additionally supports prefix listing and
backup-only deletion. Media uses `media/<existing SHA256 filename>`; invoice files
use `exports/<existing filename>`. A successful remote upload is downloaded and
verified before success is reported. Recipe hashes derive from normalized JPEG
bytes. Imported thumbnails retain their original names (the prefix can refer to
the source image, so migration separately verifies each object's actual hash).

## Migration

Run locally against the **checked cutover snapshot**, with credentials already in
the process environment. Do not place credentials in arguments or tracked files.
From `inventory_app`:

```text
python tools/migrate_media.py --media-dir <snapshot/media> --exports-dir <snapshot/exports> --manifest <private-output/objects.json>
```

The tool preserves database filenames, checks every remote object's actual SHA256,
refuses conflicting existing bytes and saves an atomic local manifest after each
verified object. Re-running resumes safely and revalidates existing remote content.
The optional exports directory preserves historical invoice downloads. Production
cutover on 2026-10-02 migrated and verified 348 objects (153,582,597 bytes), preserving
existing database references. Cloud original-Excel import is disabled;
source reconciliation and snapshot migration remain local operations.

## Backups and restore validation

The authenticated and CSRF-protected `POST /api/backups` queues the configured
`BACKUP_JOB_RESOURCE` Cloud Run Job and returns HTTP 202 `{"queued":true}`.
`/api/meta` reports `backup_pending`; another button press returns HTTP 409 while
the durable pending intent exists. The request never downloads the media archive.
The runtime service account needs only `run.jobs.run` on that one Job; it obtains
a temporary OAuth token from the fixed Google metadata endpoint. No operation
polling permission is required.

The Job executes:

```text
python tools/cloud_backup.py backup
```

The job needs `DATABASE_URL` for its `backup_runs` record, the storage environment,
`DATABASE_SCHEMA` (default `duck`), and an installed `pg_dump` version compatible
with the PostgreSQL server. `PG_DUMP_BIN` can select the binary. Set
`BACKUP_DATABASE_URL` to a separate backup role/connection when needed; otherwise
`DATABASE_URL` supplies read access for dumping. `pg_dump` receives credentials in
a temporary mode-0600 libpq service file, never command-line arguments or logs.
Use TLS certificate validation in both connection strings. Dedicated jobs can use
a session/direct connection for `pg_dump`; verify it against the actual provider.

A custom-format `database.dump` captures one consistent PostgreSQL snapshot. The
ZIP also includes `manifest.json` with the dump hash, schema, timestamp and actual
hash/size of every remote media/export object. Objects are uploaded before their
DB references commit and remain immutable; listing after the dump therefore covers
snapshot references. Keep seven daily snapshots (one per day); retention deletes
only backup ZIPs and never media/export objects that older snapshots may need.
Configure one task, parallelism one and `--max-retries=0`. The worker clears only
its matching pending intent after recording success or failure. Do not create a
daily schedule by default: reading 146.47 MiB daily consumes approximately 4.3 GiB
of monthly storage egress before customer traffic. Manual backups remain explicit.

Download an independently verified offline restore bundle to a **new directory**:

```text
python tools/cloud_backup.py download --key backups/<filename>.zip --output <new-private-directory>
```

The command verifies the archive hash, dump hash and every media/export hash/size.
It only publishes the output directory once all checks pass. It does not modify a
database. Use a compatible `pg_restore` with `--no-owner --no-acl --exit-on-error`
against an **empty isolated database** to validate `database.dump`, then apply
runtime grants with the migration tool. Compare all rows/references and exercise
the restored application before claiming recovery succeeds. Never pass live
production credentials or `--clean` during a restore rehearsal.

Real Supabase upload/download, pg_dump/pg_restore and restart durability remain
required deployment acceptance checks; local tests simulate the external HTTP and
pg_dump boundaries and do not replace these checks.


## Recover an uncertain job launch

A timeout or invalid response after `jobs.run` may mean Google accepted the job.
The app therefore retains `cloud_backup_pending` and never automatically retries.
Cancellation before the worker starts, or killing the worker, can also leave this
marker. A failed metadata-token request or definite API rejection clears it safely.

An operator must first list/inspect the configured Job's executions in Cloud Run,
confirm the submitted execution has finished (or was never created), and ensure
there is no running/queued backup. Check the most recent `duck.backup_runs` entry
and verify a successful archive before describing a backup as complete. Then use
the database admin connection to inspect the pending intent:

```sql
SELECT value::jsonb->>'id' AS pending_id,
       value::jsonb->>'submitted_at' AS submitted_at,
       value::jsonb->>'operation' AS operation
FROM duck.metadata WHERE key='cloud_backup_pending';
```

Only after that external-state check, remove the **same inspected ID**, so a newer
request cannot accidentally be cleared:

```sql
DELETE FROM duck.metadata
WHERE key='cloud_backup_pending'
  AND value::jsonb->>'id'='<confirmed-pending-id>';
```

Refresh the merchant page; the backup button can now submit one new execution.
Do not clear the marker just because an HTTP request timed out, and do not run an
extra operator-triggered execution while the existing execution is pending.
