import logging

from fastapi import APIRouter, Header, HTTPException

from udi_connectors import RuleTransform, SqlTransform, create_source, list_targets, migrate_all

from ..auth import decode_token
from ..metadata_storage import get_connection, list_connections, save_connection
from ..schemas import (
    ConnectionCreate,
    ConnectionListResponse,
    ConnectionMigrateRequest,
    ConnectionResponse,
    ConnectionTestResponse,
    DatabaseListResponse,
    MigrationResponse,
    PublishRequest,
    QueryRequest,
    QueryResponse,
    TableListResponse,
    TransformRequest,
)
from ..tasks import run_migration, run_publish, run_transform

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


def _build_config(req: ConnectionCreate) -> dict:
    source_fields = {
        "postgresql": {
            "host", "port", "database", "username", "password",
            "ssl_mode", "ssl_cert", "ssl_key", "ssl_root_cert",
            "pool_min_size", "pool_max_size", "pool_timeout",
            "batch_size", "incremental_column", "cursor_name", "checkpoint_file",
        },
        "mongodb": {
            "connection_string", "database", "max_pool_size",
            "batch_size", "incremental_field", "checkpoint_file",
        },
        "sql": {
            "host", "port", "database", "username", "password",
            "dialect", "driver", "extra_params", "pool_size", "max_overflow",
            "batch_size", "incremental_column", "checkpoint_file",
        },
        "file_upload": {
            "input_dir", "file_pattern", "recursive", "include_content", "files",
            "batch_size", "checkpoint_file",
        },
        "athena": {
            "database", "region", "catalog", "workgroup", "output_location",
            "access_key", "secret_key", "session_token",
            "batch_size", "incremental_column", "checkpoint_file",
        },
    }
    allowed = source_fields.get(req.source_type, set())
    config = {}
    for f in allowed:
        val = getattr(req, f, None)
        if val is not None:
            config[f] = val
    return config


def _get_user_id(authorization: str | None = None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user_id


@router.post("", response_model=ConnectionResponse)
async def create_connection(req: ConnectionCreate, authorization: str = Header(None)):
    user_id = _get_user_id(authorization)
    logger.info("POST /connections: name=%s type=%s user=%s", req.name, req.source_type, user_id[:8])
    config = _build_config(req)
    conn_id = await save_connection(req.name, req.source_type, config, req.description, user_id)
    return ConnectionResponse(
        id=conn_id,
        name=req.name,
        description=req.description,
        source_type=req.source_type,
        config=config,
        created_at=None,
    )


@router.post("/test", response_model=ConnectionTestResponse)
async def test_connection(req: ConnectionCreate, authorization: str = Header(None)):
    _ = _get_user_id(authorization)
    logger.info("POST /connections/test: name=%s type=%s", req.name, req.source_type)
    config = _build_config(req)
    connector, cfg = create_source(req.source_type, **config)
    try:
        await connector.connect(cfg)
        if not await connector.test_connection():
            raise HTTPException(status_code=400, detail="Connection test failed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection test failed: {e}")
    finally:
        await connector.disconnect()
    return ConnectionTestResponse(status="ok", message="Connection test successful")


@router.get("", response_model=ConnectionListResponse)
async def list_all_connections(authorization: str = Header(None)):
    user_id = _get_user_id(authorization)
    logger.info("GET /connections user=%s", user_id[:8])
    connections = await list_connections(user_id)
    return ConnectionListResponse(connections=connections)


@router.post("/{conn_id}/tables", response_model=TableListResponse)
async def get_tables(conn_id: str):
    logger.info("POST /connections/%s/tables", conn_id[:8])
    record = await get_connection(conn_id)
    if not record:
        raise HTTPException(status_code=404, detail="Connection not found")

    source_type = record["source_type"]
    config = record["config"]

    connector, cfg = create_source(source_type, **config)
    try:
        await connector.connect(cfg)
        tables = await connector.list_tables(cfg)
        logger.info("Found %d tables for connection %s", len(tables), conn_id[:8])
        return TableListResponse(tables=tables)
    finally:
        await connector.disconnect()


@router.post("/{conn_id}/databases", response_model=DatabaseListResponse)
async def get_databases(conn_id: str):
    logger.info("POST /connections/%s/databases", conn_id[:8])
    record = await get_connection(conn_id)
    if not record:
        raise HTTPException(status_code=404, detail="Connection not found")
    source_type = record["source_type"]
    config = record["config"]
    connector, cfg = create_source(source_type, **config)
    try:
        await connector.connect(cfg)
        databases = await connector.list_databases(cfg)
        logger.info("Found %d databases for connection %s", len(databases), conn_id[:8])
        return DatabaseListResponse(databases=databases)
    finally:
        await connector.disconnect()


@router.post("/{conn_id}/query", response_model=QueryResponse)
async def run_query(conn_id: str, req: QueryRequest, authorization: str = Header(None)):
    user_id = _get_user_id(authorization)
    logger.info("POST /connections/%s/query user=%s", conn_id[:8], user_id[:8])
    record = await get_connection(conn_id)
    if not record:
        raise HTTPException(status_code=404, detail="Connection not found")

    source_type = record["source_type"]
    if source_type != "athena":
        raise HTTPException(status_code=400, detail=f"Ad-hoc queries are not supported for source type '{source_type}'")

    config = record["config"]
    connector, cfg = create_source(source_type, **config)
    try:
        await connector.connect(cfg)
        result = await connector.execute_query(req.sql)
        return QueryResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query failed: {e}")
    finally:
        await connector.disconnect()


@router.post("/{conn_id}/migrate", response_model=MigrationResponse, status_code=202)
async def migrate_from_connection(conn_id: str, req: ConnectionMigrateRequest):
    logger.info("POST /connections/%s/migrate: tables=%s", conn_id[:8], req.tables)
    record = await get_connection(conn_id)
    if not record:
        raise HTTPException(status_code=404, detail="Connection not found")

    source_type = record["source_type"]
    source_config = record["config"]
    connection_name = record.get("name")

    # Stage 2/3 read the raw zone by connection_id + table_name, so the S3
    # target needs to know which connection this landing belongs to. A
    # caller-supplied connection_id in target_config (if any) wins.
    target_config = dict(req.target_config)
    target_config.setdefault("connection_id", conn_id)

    task_id = await run_migration(
        source=source_type,
        target="s3",
        tables=req.tables,
        source_config=source_config,
        target_config=target_config,
        connection_id=conn_id,
        connection_name=connection_name,
    )
    return MigrationResponse(
        task_id=task_id,
        status="running",
        message="Migration started",
    )


@router.post("/{conn_id}/transform", response_model=MigrationResponse, status_code=202)
async def transform_connection(conn_id: str, req: TransformRequest):
    """Stage 2: read the raw zone this connection already landed (Athena SQL,
    or the direct S3 reader as a fallback), transform it, land the result in
    curated/{connection}/{table}__staging/."""
    logger.info("POST /connections/%s/transform: table=%s source_type=%s", conn_id[:8], req.table_name, req.source_type)
    record = await get_connection(conn_id)
    if not record:
        raise HTTPException(status_code=404, detail="Connection not found")
    connection_name = record.get("name")

    if req.sql:
        transform = SqlTransform(sql=req.sql)
        persist = {"type": "sql", "sql": req.sql}
    elif req.rule:
        transform = RuleTransform(
            rename=req.rule.rename,
            cast=req.rule.cast,
            drop_columns=req.rule.drop_columns,
            drop_nulls=req.rule.drop_nulls,
            dedupe_keys=req.rule.dedupe_keys,
        )
        persist = {"type": "rule", **req.rule.model_dump()}
    else:
        transform = None
        persist = {"type": "none"}

    task_id = await run_transform(
        connection_id=conn_id,
        table_name=req.table_name,
        transform=transform,
        source_type=req.source_type,
        source_config=req.source_config,
        target_config=req.target_config,
        batch_size=req.batch_size,
        connection_name=connection_name,
        persist_transform=persist,
    )
    return MigrationResponse(
        task_id=task_id,
        status="running",
        message="Transform started",
    )


@router.post("/{conn_id}/publish", response_model=MigrationResponse, status_code=202)
async def publish_connection(conn_id: str, req: PublishRequest):
    """Stage 3: check whether the published curated dataset already exists,
    then create / append / upsert Stage 2's staged increment into it."""
    logger.info("POST /connections/%s/publish: table=%s merge_keys=%s", conn_id[:8], req.table_name, req.merge_keys)
    record = await get_connection(conn_id)
    if not record:
        raise HTTPException(status_code=404, detail="Connection not found")
    connection_name = record.get("name")

    task_id = await run_publish(
        connection_id=conn_id,
        table_name=req.table_name,
        merge_keys=req.merge_keys,
        target_config=req.target_config,
        connection_name=connection_name,
    )
    return MigrationResponse(
        task_id=task_id,
        status="running",
        message="Publish started",
    )
