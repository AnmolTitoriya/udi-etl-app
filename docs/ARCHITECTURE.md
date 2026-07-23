# Unified Data Integration & ETL Platform — Architecture

This document explains the purpose and responsibilities of every layer/
service in the platform, from the browser down to the AWS resources it
manages on the user's behalf. It replaces the previous architecture write-up
that lived in Google Drive — this is now the source of truth, versioned
alongside the code.

The platform spans four repos:

| Repo | Layer |
|---|---|
| [`udi-etl-web`](../../udi-etl-web) | Client Layer — React Web Portal |
| [`udi-etl-app`](../) | Gateway + Core Services — REST API, connections, migrations |
| [`udi-connectors`](../../udi-connectors) | Connector implementations used by the Core Services |
| [`udi-packages`](../../udi-packages) | Shared connector interfaces/contracts |

Note: this document describes the platform's intended end-state
architecture. Several services below (full multi-tenancy, Domains,
Parameter Store, Scheduler) are planned and not yet implemented, and others
(Auth, ETL Jobs) are further along than the original design doc assumed —
see each section's **Status** line for what exists today versus what's on
the roadmap. For the implemented API surface, see [`USAGE.md`](USAGE.md).

## 1. Client Layer

### React Web Portal

The single front-end application end users interact with (`udi-etl-web`).
It gives tenants a unified UI for managing connections, datasets, ETL jobs,
secrets, and schedules — so nobody needs to open the AWS Console directly.
All actions in the portal are translated into calls against the REST API
Layer.

**Status:** implemented for the connector → schema → target → run flow (see
`udi-etl-web/README.md`). Secrets/schedule management UI is planned.

## 2. Gateway Layer

### REST API Layer

The entry point for every request into the platform, whether it comes from
the web portal or a future external integration. It exposes a stable,
versioned API surface that hides the underlying AWS complexity, and (once
implemented) forwards authenticated requests down to the Auth & Tenant
Service.

**Status:** implemented as the FastAPI service in this repo (`api/`). See
[`USAGE.md`](USAGE.md) for the full endpoint reference. Auth/tenant
forwarding is not yet wired in — see below.

## 3. Core Services

### Auth & Tenant Service

Sits right behind the API layer and is responsible for two things on every
single request: **who is calling** (authentication/identity) and **which
tenant they belong to** (tenant resolution). Every downstream module
receives a validated Tenant ID, which is what makes strict multi-tenant
isolation possible — resources, metadata, and logs are scoped by tenant at
this layer and enforced everywhere below it.

**Status:** partially implemented. `POST /auth/signup`, `POST /auth/login`,
and `GET /auth/me` (`api/routes/auth.py`) provide password-based signup/login
with PBKDF2-HMAC password hashing and a JWT access token
(`api/auth.py`); connections are created and listed scoped to the
authenticated `user_id` (`api/routes/connections.py`). There is no
organization/Tenant concept above the individual user yet — no roles, no
tenant-scoped isolation beyond "owned by this user_id", and several routes
(`/connections/{id}/tables`, `/databases`, `/migrate`, `/transform`,
`/publish`) don't require authentication at all today.

### Connections

Establishes secure connectivity between the platform and external systems.
A Connection is a reusable object — created once, referenced by many
Datasets and ETL Jobs — that handles **authentication and communication
only**; it never moves or transforms data itself.

- **Supported types today:** PostgreSQL, MongoDB, generic SQL (MySQL, MSSQL,
  Oracle, SQLite via SQLAlchemy), local file upload, Amazon Athena, Amazon
  S3 — see [`udi-connectors`](../../udi-connectors/README.md) for the
  per-connector docs.
- **Planned (from the original platform scope):** Oracle/Redshift/Aurora as
  first-class connection types, REST APIs, generic JDBC, SQL Server,
  MariaDB, Azure Blob Storage, Google Cloud Storage, MinIO, GraphQL, ODBC.
- **Stores:** name, type, host, port, credentials, plus connector-specific
  fields (see each connector's README) — persisted via the `connections`
  table in the metadata database (see [`USAGE.md`](USAGE.md)).
- **AWS mapping (target state):** AWS Glue Connections, IAM Roles, VPC
  configuration, Security Groups, and Secrets Manager for credential
  storage. Today, credentials are stored directly in the metadata database.

### Tenant

Represents a single organization/customer on the platform, with complete
isolation from every other tenant. A Tenant owns everything created under it
— Connections, Domains, Datasets, ETL Jobs, Parameters, Scheduler jobs,
logs, and metadata — and is responsible for its own user management, role
management, and audit logging (billing is planned for a future release).

**Status:** planned — not implemented.

### Domains

A logical grouping for Datasets within a tenant — conceptually equivalent to
an AWS Glue Database. Instead of organizing data by where it physically
lives, Domains let teams organize it by business area (e.g. *Finance*,
*Sales*, *Marketing*, *HR*, *Operations*), which simplifies governance,
access control, and discovery.

- **Maps to:** an AWS Glue Database, with additional platform-level metadata
  (ownership, tags, descriptions) layered on top for search and governance.

**Status:** planned — not implemented.

### Datasets

Represents a structured collection of data inside a Domain — analogous to a
table. The platform stores the *metadata* for a dataset (name, domain,
source/destination connection, schema, table name, file format,
partitioning, description, tags, owner, Tenant ID); the actual data stays
wherever it already lives (S3, Redshift, Aurora, PostgreSQL, Oracle, MySQL,
or another external database).

- **Maps to:** the AWS Glue Data Catalog, plus S3 and/or the Redshift
  Catalog where applicable.

**Status:** partially implemented — migrations record source table, target
S3 location, and file format in the `migrations` table, but there's no
standalone Dataset/Domain catalog yet.

### ETL Jobs

Defines how data actually moves and transforms — the source, the
destination, and the transformation logic in between.

**Status:** implemented as a 3-stage raw → curated pipeline
(`udi_connectors.pipeline`, orchestrated via `api/tasks.py`):

1. **Stage 1 — land** (`POST /connections/{id}/migrate`, or `POST /migrate`
   for an ad-hoc source/target pair not tied to a saved connection): reads
   the source connector and writes straight to S3's `raw` zone.
2. **Stage 2 — transform** (`POST /connections/{id}/transform`): reads the
   raw zone back — via Athena SQL (`SqlTransform`, requires
   `source_type="athena"`) or a declarative pyarrow-level `RuleTransform`
   (rename/cast/drop columns/drop nulls/dedupe by key, works against either
   Athena or the plain S3 reader) — and lands the result as an isolated
   `{table}__staging` increment under the `curated` zone.
3. **Stage 3 — publish** (`POST /connections/{id}/publish`): checks whether
   the published curated dataset already exists and, based on that plus
   whether `merge_keys` were given, does exactly one of **create** (first
   write), **append** (no merge keys), or **upsert** (delete-then-rewrite by
   key) — then clears the staging increment. Schema drift between the
   previous and newly-published schema is detected and logged as a warning
   (the Glue table itself isn't auto-altered; a crawler re-run or manual
   `ALTER TABLE` is needed before querying the new columns via Athena).

All three stages are async background tasks; poll `GET /migrate/{task_id}`
for status/result of any of them (the `stage` field on the `migrations` row
records which one a given run belongs to). See [`USAGE.md`](USAGE.md) for
the full request/response shapes.

- **Planned:** a query-builder / visual ETL designer in the web portal (SQL
  and rule transforms already work — just not yet through a friendly editor
  UI), reusable transform templates, and non-Athena engines for the SQL
  transform path (Spark/PySpark).
- **Stores:** migration/job id, connection, stage (`landed`/`transformed`/
  `published`), tables, status, result, error, S3 folder, created_at — see
  the `migrations` table schema in [`USAGE.md`](USAGE.md). A connection's
  chosen transform config and merge keys persist on the `connections` row
  (`transform_config`, `merge_keys`) so Stage 2/3 can be re-run without
  re-specifying them.
- **AWS mapping (target state):** AWS Glue Jobs (with Glue Interactive
  Sessions planned) and CloudWatch Logs for execution output. Today, all
  three stages run in-process in the FastAPI service, using Athena for SQL
  execution and S3 directly for storage, and log to stdout.

### Parameter Store

Secure storage for sensitive configuration values used across the platform
— database passwords, API keys, OAuth/access tokens, JDBC credentials,
encryption keys, and runtime variables. Everything here would be encrypted,
access-controlled, and never exposed in plain text to anyone without the
right role.

- **Planned features:** encrypted storage, versioning, role-based access,
  audit logging, environment-specific parameters, secret rotation.
- **AWS mapping (target state):** AWS Secrets Manager (preferred for actual
  secrets), Systems Manager Parameter Store (for non-secret configuration),
  and KMS for key management.

**Status:** planned. Connection passwords today are masked in API responses
(`"****"`) but stored as plain values in the metadata database — see
[`USAGE.md`](USAGE.md) for current behavior.

### Scheduler

Automates when ETL Jobs run, so nothing has to be triggered by hand. It
would offer the same core capability as native AWS Glue scheduling, through
one simplified interface.

- **Planned scheduling options:** one-time, hourly, daily, weekly, monthly,
  raw cron expressions, event-based triggers.
- **Planned features:** retry policies, failure notifications, job history,
  execution logs, enable/disable toggles, dependency management.
- **AWS mapping (target state):** Amazon EventBridge Scheduler and AWS Glue
  Triggers (CloudWatch Events for legacy cases).

**Status:** planned — not implemented. Migrations run on-demand only.

## 4. AWS Service Wrapper

The thin translation layer between the platform's modules and the real AWS
resources underneath them. In the target architecture, every module above
calls into this wrapper rather than talking to AWS directly, so the
platform can simplify AWS's complexity for users without duplicating or
replacing any of AWS's native capability.

**Status:** today, AWS calls (S3, Athena) are made directly from the
relevant connector in `udi-connectors` via `boto3` — there's no separate
wrapper layer yet.

## 5. AWS Managed Services

These are the real AWS services the platform orchestrates. The platform
doesn't own or replace any of them — it manages them centrally on the
user's behalf.

| Service | Role in the platform |
|---|---|
| **AWS Glue** | Runs ETL jobs and backs the Data Catalog (Domains/Datasets), including future Spark and interactive sessions *(planned — Glue's Data Catalog is used indirectly today, since Athena queries registered Glue tables, but there are no Glue Jobs)* |
| **Amazon Athena** | Runs Stage 2 SQL transforms and ad-hoc queries against the Glue Catalog *(implemented — see the [`athena` connector](../../udi-connectors/src/udi_connectors/athena/README.md))* |
| **Amazon S3** | Object storage for the raw/curated data lake and ETL staging *(implemented — see the [`s3` connector](../../udi-connectors/src/udi_connectors/s3/README.md))* |
| **AWS Secrets Manager** | Secure storage for connection credentials and platform secrets *(planned — credentials are stored as plain values in the metadata database today, masked only in API responses)* |
| **IAM** | Roles and permissions underlying Connections and all AWS resource access *(implemented via access key/secret or default credential chain)* |
| **CloudWatch** | Centralized logging for ETL Job execution *(planned — logging is local/stdout today)* |
| **EventBridge Scheduler** | Executes the Scheduler module's schedules and triggers Glue jobs *(planned)* |

## 6. Cross-Cutting: Security Model

In the target architecture, the following is applied on every single
operation across every module above, not just at the API boundary:

- Tenant ID validation
- User identity verification
- Role-based permission checks
- Resource ownership checks

Secrets would stay encrypted both at rest and in transit throughout.

**Status:** partially implemented. User identity verification exists (JWT,
`GET /auth/me`) and connections/migrations are associated with a `user_id`,
but tenant validation, role-based permission checks, and resource-ownership
checks are not enforced consistently across every route yet — see the Auth
& Tenant Service section above.
