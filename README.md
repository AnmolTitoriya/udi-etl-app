# udi-etl-app

FastAPI service that exposes [`udi-connectors`](../udi-connectors) over HTTP:
save/test connections, browse tables & databases, kick off migrations to S3,
and poll migration status. Backs the [`udi-etl-web`](../udi-etl-web) console.

Migration + connection history is persisted to a PostgreSQL "metadata"
database (`data_migration_meta`), separate from any source/target databases
being migrated.

## Setup

```bash
uv sync
cp .env.example .env   # fill in AWS/PG/Mongo/metadata-DB values
python seed_metadata_db.py   # creates data_migration_meta + demo_source DBs
uv run uvicorn api.main:app --reload --port 8001
```

Open `http://localhost:8001/docs` for the interactive Swagger UI. See
[`docs/USAGE.md`](docs/USAGE.md) for the full API reference, and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how this service fits
into the wider platform (client, gateway, core services, AWS mapping) and
what's implemented versus planned.

This assumes `udi-connectors` and `udi-packages` are checked out as sibling
directories (`../udi-connectors`, `../udi-packages`), per the
`[tool.uv.sources]` path dependencies in `pyproject.toml`. Swap those for git
dependencies once those repos live at stable remotes.

## Other scripts

- `run_migrate.py` — standalone demo script: seeds a Postgres table and
  migrates it straight to S3, no API server involved.
- `docker-compose.yml` — spins up local `postgres:16` (port 5433) and
  `mongo:7` containers, primarily for exercising `udi-connectors`' test
  suite against real databases.
