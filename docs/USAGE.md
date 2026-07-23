# How to use this thing

This tool moves data from databases (PostgreSQL, MongoDB, MySQL, etc.) or local files into S3 as CSV, Parquet, or JSONL.

There are two ways to use it:

1. **Via the API** — send HTTP requests to a server
2. **Via Python imports** — call the functions directly in your code

---

# Part 1: Using the API

## Start the server

```bash
uv run uvicorn api.main:app --reload --port 8001
```

Open `http://localhost:8001/docs` for the interactive Swagger UI.

## All endpoints

| Method | URL | Auth required | What it does |
|--------|-----|:---:|-------------|
| `GET` | `/health` | | Check if server is alive |
| `POST` | `/auth/signup` | | Create a user, returns a JWT |
| `POST` | `/auth/login` | | Log in, returns a JWT |
| `GET` | `/auth/me` | ✓ | Get the current user from the token |
| `GET` | `/sources` | | See what source types are available |
| `GET` | `/targets` | | See what target types are available |
| `GET` | `/sources/{name}/schema` | | Field descriptors for a source's config (drives dynamic forms) |
| `GET` | `/targets/{name}/schema` | | Field descriptors for a target's config |
| `POST` | `/connections` | ✓ | Save a connection under the current user |
| `POST` | `/connections/test` | ✓ | Test connection details without saving them |
| `GET` | `/connections` | ✓ | List the current user's saved connections |
| `POST` | `/connections/{id}/databases` | | List databases on that server |
| `POST` | `/connections/{id}/tables` | | List tables in that database |
| `POST` | `/connections/{id}/query` | ✓ | Run an ad-hoc SQL query (Athena connections only) |
| `POST` | `/connections/{id}/migrate` | | Stage 1: migrate a saved connection's tables to S3 (raw zone) |
| `POST` | `/migrate` | | Stage 1, ad-hoc: migrate directly, no saved connection |
| `POST` | `/connections/{id}/transform` | | Stage 2: transform the raw zone into a curated staging increment |
| `POST` | `/connections/{id}/publish` | | Stage 3: publish the staged increment into the curated dataset |
| `GET` | `/migrate/{task_id}` | | Check status of any stage (migrate/transform/publish) by task id |

Routes marked "Auth required" expect an `Authorization: Bearer <token>`
header, using the token from `/auth/signup` or `/auth/login`. The
listing/table/database/migrate/transform/publish routes that take a
`{conn_id}` don't currently check the token against connection ownership —
see [`ARCHITECTURE.md`](ARCHITECTURE.md) for the current state of the auth
model.

A demo user is seeded on first startup: `demo@example.com` / `demo123`.

---

## 0. Authentication

**Sign up — POST /auth/signup**
```json
{ "email": "me@example.com", "password": "hunter2", "name": "Me" }
```

**Log in — POST /auth/login**
```json
{ "email": "me@example.com", "password": "hunter2" }
```

Both return:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": { "id": "abc-123", "email": "me@example.com", "name": "Me" }
}
```

Send `Authorization: Bearer <access_token>` on `POST /connections`,
`POST /connections/test`, `GET /connections`, and `GET /auth/me`.

---

## 1. Create a connection — POST /connections

Save your database details so you don't have to send them every time. The API connects and checks credentials before saving.

**Minimal for PostgreSQL:**
```json
{
  "name": "My Aiven PG",
  "source_type": "postgresql",
  "host": "pg-1234.aivencloud.com",
  "port": 27726,
  "database": "defaultdb",
  "username": "avnadmin",
  "password": "your-password",
  "ssl_mode": "require"
}
```

**Minimal for MongoDB:**
```json
{
  "name": "My MongoDB",
  "source_type": "mongodb",
  "connection_string": "mongodb://localhost:27017",
  "database": "mydb"
}
```

**Minimal for SQL (MySQL, MSSQL, Oracle, SQLite):**
```json
{
  "name": "My MySQL",
  "source_type": "sql",
  "dialect": "mysql",
  "host": "localhost",
  "port": 3306,
  "database": "mydb",
  "username": "root",
  "password": "pass"
}
```

**Minimal for File Upload:**
```json
{
  "name": "My Files",
  "source_type": "file_upload",
  "input_dir": "C:/data/files"
}
```

**Minimal for Athena:**
```json
{
  "name": "My Athena",
  "source_type": "athena",
  "database": "analytics",
  "workgroup": "primary",
  "output_location": "s3://my-athena-results/",
  "region": "us-east-1"
}
```

Credentials for Athena (`access_key`/`secret_key`/`session_token`) are optional
— omit them to fall back to the default boto3 credential chain (IAM role, env
vars, `~/.aws/credentials`).

All optional fields you can include:

| Field | For source | Default |
|-------|-----------|---------|
| `ssl_mode` | postgresql | `"prefer"` |
| `ssl_cert` | postgresql | null |
| `ssl_key` | postgresql | null |
| `ssl_root_cert` | postgresql | null |
| `pool_min_size` | postgresql | 2 |
| `pool_max_size` | postgresql | 10 |
| `pool_timeout` | postgresql | 30.0 |
| `batch_size` | all | 20000 |
| `incremental_column` | postgresql, sql, athena | null |
| `incremental_field` | mongodb | null |
| `cursor_name` | postgresql | null |
| `checkpoint_file` | all | null |
| `max_pool_size` | mongodb | 10 |
| `driver` | sql | null |
| `extra_params` | sql | null |
| `pool_size` | sql | 5 |
| `max_overflow` | sql | 10 |
| `file_pattern` | file_upload | `"*"` |
| `recursive` | file_upload | false |
| `include_content` | file_upload | false |
| `files` | file_upload | null |
| `region` | athena | `"us-east-1"` |
| `catalog` | athena | `"AwsDataCatalog"` |
| `workgroup` | athena | `"primary"` |
| `output_location` | athena | null (required unless the workgroup has a default) |
| `access_key` / `secret_key` / `session_token` | athena | null (falls back to boto3 default credential chain) |

**Response:** `{ "id": "abc-123", "name": "...", "source_type": "...", "config": {...}, "created_at": "..." }`

---

## 2. List connections — GET /connections

Returns all saved connections. Passwords are hidden (`"****"`).

**Response:**
```json
{
  "connections": [
    {
      "id": "abc-123",
      "name": "My Aiven PG",
      "source_type": "postgresql",
      "config": { "host": "...", "password": "****", ... },
      "created_at": "2026-07-16T..."
    }
  ]
}
```

---

## 3. List databases — POST /connections/{id}/databases

Shows all databases on that server. No request body needed.

**Response:** `{ "databases": ["demo_source", "postgres", "data_migration_meta"] }`

---

## 4. List tables — POST /connections/{id}/tables

Shows all tables in the database. No request body needed.

**Response:** `{ "tables": ["users", "orders", "products"] }`

---

## 5. Migrate from saved connection — POST /connections/{id}/migrate

Uses the saved connection config. You only need to specify which tables and the S3 target.

```json
{
  "tables": ["users", "orders"],
  "target_config": {
    "bucket_name": "dash-data-migration",
    "region": "ap-south-1",
    "access_key": "YOUR_AWS_KEY",
    "secret_key": "YOUR_AWS_SECRET",
    "file_format": "parquet",
    "compression": "snappy"
  }
}
```

**target_config options:**

| Field | Required | Default |
|-------|----------|---------|
| `bucket_name` | **Yes** | — |
| `region` | No | `us-east-1` |
| `access_key` | No | from env or IAM |
| `secret_key` | No | from env or IAM |
| `session_token` | No | null |
| `prefix` | No | `""` |
| `file_format` | No | `parquet` |
| `compression` | No | `snappy` |
| `batch_size` | No | 100000 |
| `max_concurrent_uploads` | No | 5 |
| `retry_count` | No | 3 |
| `retry_delay` | No | 1.0 |

**Response:** `{ "task_id": "xyz-789", "status": "running", "message": "Migration started" }`

---

## 6. Direct migrate — POST /migrate (no saved connection)

Same as #5 but you send the full source config inline. Works the same as before.

```json
{
  "source": "postgresql",
  "target": "s3",
  "tables": ["users"],
  "source_config": {
    "host": "pg-1234.aivencloud.com",
    "port": 27726,
    "database": "defaultdb",
    "username": "avnadmin",
    "password": "your-password",
    "ssl_mode": "require"
  },
  "target_config": {
    "bucket_name": "dash-data-migration",
    "region": "ap-south-1"
  }
}
```

---

## 6a. Transform (Stage 2) — POST /connections/{id}/transform

Reads back what Stage 1 landed in the S3 raw zone, optionally transforms
it, and lands the result as an isolated `{table}__staging` increment under
the curated zone. Two transform options, both optional (omit both to just
copy raw → curated staging untouched):

**SQL transform** (requires the connection's `source_type` to be
`"athena"` — the SQL runs against Athena over the raw zone):
```json
{
  "table_name": "orders",
  "sql": "SELECT id, customer_id, total FROM orders WHERE total > 0"
}
```

**Rule transform** (works against Athena or the plain S3 fallback reader):
```json
{
  "table_name": "orders",
  "rule": {
    "rename": { "cust_id": "customer_id" },
    "cast": { "total": "float64" },
    "drop_columns": ["internal_notes"],
    "drop_nulls": ["customer_id"],
    "dedupe_keys": ["id"]
  }
}
```

`source_type` defaults to `"athena"`; pass `"s3"` to use the direct S3
reader instead (required if a SQL transform isn't being used and Athena
isn't provisioned for this connection). `source_config`/`target_config`
override the connection's stored config for this run only.

**Response:** `{ "task_id": "...", "status": "running", "message": "Transform started" }` — poll it the same way as a migration.

---

## 6b. Publish (Stage 3) — POST /connections/{id}/publish

Moves Stage 2's staged increment into the published curated dataset.

```json
{
  "table_name": "orders",
  "merge_keys": ["id"]
}
```

Omit `merge_keys` for a plain append. The connector checks whether the
table already exists and picks **create** (first write), **append** (no
merge keys), or **upsert** (delete-then-rewrite by `merge_keys`)
accordingly, then clears the staging increment. A schema change between the
previous and newly-published columns is logged as a warning but does not
block the publish — the Glue table definition isn't auto-updated, so a
crawler re-run (or manual `ALTER TABLE`) is needed before querying new
columns via Athena.

**Response:** `{ "task_id": "...", "status": "running", "message": "Publish started" }` — poll it the same way as a migration; the result shape is `PublishResultSchema` (`action`, `schema_changed`, `rows_loaded`, `batch_count`, `errors`).

---

## 7. Check status — GET /migrate/{task_id}

**When running:**
```json
{ "status": "running", "result": null, "error": null }
```

**When done:**
```json
{
  "status": "completed",
  "result": [
    { "table_name": "users", "rows_loaded": 50000, "batch_count": 1, "errors": [] }
  ],
  "error": null
}
```

**When failed:**
```json
{ "status": "failed", "result": null, "error": "relation \"users\" does not exist" }
```

---

## S3 folder structure

Each migration creates a folder in S3 named after the **task_id** (UUID). Every table in that migration goes into the same folder.

```
my-bucket/
  └── abc123-def-456/            ← task_id
       ├── users_0.parquet
       ├── users_1.parquet
       └── orders_0.parquet
```

You can find the data for any migration by looking up the task_id. The metadata database also stores the task_id and s3_folder for every migration.

---

## Migration history in the database

Every migration is automatically saved in the `migrations` table of the metadata database (`data_migration_meta`). You can query it directly in pgAdmin:

```sql
SELECT * FROM migrations ORDER BY created_at DESC;
```

| Column | What it stores |
|--------|---------------|
| id | task_id (UUID) — also the S3 folder name |
| connection_id | Which connection was used |
| connection_name | User-friendly name of the connection |
| source_type | postgresql / mongodb / sql / file_upload |
| target_type | s3 |
| tables | JSON list of table names migrated |
| status | running / completed / failed |
| result | JSON with rows_loaded per table |
| error | Error message if failed |
| s3_folder | Same as id — the S3 folder where data is stored |
| created_at | When the migration started |

---

## Retry behavior

Each table gets 3 automatic retries. If a batch fails, it waits 0s, then 2s, then 4s. Checkpoint is saved after each successful batch upload. If the whole thing crashes, the next run picks up from the last checkpoint.

---

# Part 2: Using Python imports directly

```python
from udi_connectors import migrate_all

results = await migrate_all(
    source_name="postgresql",
    target_name="s3",
    tables=["customers"],
    source_kwargs={
        "host": "db.example.com",
        "port": 5432,
        "database": "mydb",
        "username": "admin",
        "password": "secret123",
    },
    target_kwargs={
        "bucket_name": "my-bucket",
        "file_format": "csv",
    },
)

print(f"Done. Moved {results[0].rows_loaded} rows")
```

The `migrate_all()` function accepts an optional `s3_folder` parameter. If you pass it, all tables go into that folder. If not, each table gets its own folder (old behavior).

```python
results = await migrate_all(
    ...,
    s3_folder="my-custom-folder-name",
)
```

---

# Metadata database setup

The API stores connections and migration history in PostgreSQL. Run this once:

```bash
python seed_metadata_db.py
```

This creates:
- Database `data_migration_meta` with tables `connections` and `migrations`
- Database `demo_source` with a `users` table containing 4 dummy rows for testing

Connection URL in `.env`:
```
METADATA_DATABASE_URL=postgresql://postgres:your_password@localhost:5432/data_migration_meta
```

---

# File formats

| Format | Extension | Notes |
|--------|-----------|-------|
| csv | .csv | Opens in Excel |
| parquet | .parquet | Fast, compressed |
| jsonl | .jsonl | One JSON per line |

Set `file_format` in target config. Compression: `none`, `snappy`, or `gzip`.
