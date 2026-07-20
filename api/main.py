import asyncio
import logging
import platform

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from udi_connectors import list_sources, list_targets

from .connector_schema import describe_source, describe_target
from .metadata_storage import init_db
from .routes.auth import router as auth_router
from .routes.connections import router as connections_router
from .schemas import (
    HealthResponse,
    MigrationRequest,
    MigrationResponse,
    SourcesResponse,
    TargetsResponse,
    TaskStatusResponse,
    LoadResultSchema,
)
from .tasks import get_task, run_migration

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Data Migration API",
    description="Async-first data migration API powered by the file package",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    logger.info("Initializing metadata database...")
    try:
        await init_db()
    except Exception as e:
        logger.warning("Could not init metadata DB: %s (proceeding anyway)", e)


app.include_router(auth_router)
app.include_router(connections_router)


@app.get("/health", response_model=HealthResponse)
async def health():
    logger.debug("Health check")
    return HealthResponse()


@app.get("/sources", response_model=SourcesResponse)
async def sources():
    return SourcesResponse(sources=list_sources())


@app.get("/targets", response_model=TargetsResponse)
async def targets():
    return TargetsResponse(targets=list_targets())


@app.get("/sources/{name}/schema")
async def source_schema(name: str):
    """Field descriptors for a source's Config class — how the wizard builds
    a form for any connector it doesn't have a hand-authored field spec for,
    built-in or custom/plugin alike."""
    fields = describe_source(name)
    if fields is None:
        raise HTTPException(status_code=404, detail=f"Unknown source: {name}")
    return {"source_type": name, "fields": fields}


@app.get("/targets/{name}/schema")
async def target_schema(name: str):
    fields = describe_target(name)
    if fields is None:
        raise HTTPException(status_code=404, detail=f"Unknown target: {name}")
    return {"target_type": name, "fields": fields}


@app.post("/migrate", response_model=MigrationResponse, status_code=202)
async def create_migration(req: MigrationRequest):
    logger.info("POST /migrate: source=%s target=%s tables=%s", req.source, req.target, req.tables)
    task_id = await run_migration(
        source=req.source,
        target=req.target,
        tables=req.tables,
        source_config=req.source_config,
        target_config=req.target_config,
    )
    return MigrationResponse(
        task_id=task_id,
        status="running",
        message="Migration started",
    )


@app.get("/migrate/{task_id}", response_model=TaskStatusResponse)
async def get_migration_status(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    result = None
    if task.result:
        result = [
            LoadResultSchema(
                destination_type=r.destination_type,
                table_name=r.table_name,
                rows_loaded=r.rows_loaded,
                batch_count=r.batch_count,
                errors=r.errors,
            )
            for r in task.result
        ]

    return TaskStatusResponse(
        task_id=task_id,
        status=task.status,
        stage=task.stage,
        result=result,
        error=task.error,
        detail=task.detail,
    )
