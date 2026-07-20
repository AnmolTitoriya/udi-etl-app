import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from udi_connectors import Transform, migrate_all, migrate_raw_to_curated, publish_curated
from udi_packages import LoadResult

from .metadata_storage import save_merge_keys, save_migration, save_transform_config, update_migration

logger = logging.getLogger(__name__)


@dataclass
class TaskEntry:
    status: str
    stage: str = "landed"
    result: list[LoadResult] | None = None
    error: str | None = None
    detail: dict[str, Any] | None = None


_tasks: dict[str, TaskEntry] = {}


def _load_result_dict(r: LoadResult) -> dict:
    return {"destination_type": r.destination_type, "table_name": r.table_name, "rows_loaded": r.rows_loaded, "batch_count": r.batch_count, "errors": r.errors}


async def run_migration(
    source: str,
    target: str,
    tables: list[str],
    source_config: dict[str, Any],
    target_config: dict[str, Any],
    connection_id: str | None = None,
    connection_name: str | None = None,
) -> str:
    task_id = str(uuid.uuid4())
    _tasks[task_id] = TaskEntry(status="running")
    logger.info("Task %s: migration started %s -> %s tables=%s", task_id[:8], source, target, tables)

    await save_migration(task_id, connection_id, connection_name, source, target, tables)

    async def _execute():
        try:
            results = await migrate_all(
                source_name=source,
                target_name=target,
                tables=tables,
                source_kwargs=source_config,
                target_kwargs=target_config,
            )
            _tasks[task_id].status = "completed"
            _tasks[task_id].result = results
            await update_migration(task_id, "completed", result=json.dumps([r.to_dict() if hasattr(r, 'to_dict') else {"table_name": r.table_name, "rows_loaded": r.rows_loaded, "batch_count": r.batch_count, "errors": r.errors} for r in results]))
            logger.info("Task %s: migration completed successfully", task_id[:8])
        except Exception as e:
            _tasks[task_id].status = "failed"
            _tasks[task_id].error = str(e)
            await update_migration(task_id, "failed", error=str(e))
            logger.error("Task %s: migration failed: %s", task_id[:8], e)

    asyncio.create_task(_execute())
    return task_id


def get_task(task_id: str) -> TaskEntry | None:
    return _tasks.get(task_id)


async def run_transform(
    connection_id: str,
    table_name: str,
    transform: Transform,
    source_type: str,
    source_config: dict[str, Any],
    target_config: dict[str, Any],
    batch_size: int | None = None,
    connection_name: str | None = None,
    persist_transform: dict | None = None,
) -> str:
    """Stage 2: raw -> curated/_staging via migrate_raw_to_curated()."""
    task_id = str(uuid.uuid4())
    _tasks[task_id] = TaskEntry(status="running", stage="transformed")
    logger.info("Task %s: transform started connection=%s table=%s", task_id[:8], connection_id[:8], table_name)

    await save_migration(task_id, connection_id, connection_name, source_type, "s3", [table_name], stage="transformed")
    if persist_transform is not None:
        await save_transform_config(connection_id, persist_transform)

    async def _execute():
        try:
            result = await migrate_raw_to_curated(
                connection_id=connection_id,
                table_name=table_name,
                transform=transform,
                source_type=source_type,
                source_kwargs=source_config,
                target_kwargs=target_config,
                batch_size=batch_size,
            )
            _tasks[task_id].status = "completed"
            _tasks[task_id].result = [result]
            await update_migration(task_id, "completed", result=json.dumps([_load_result_dict(result)]), stage="transformed")
            logger.info("Task %s: transform completed: rows=%d batches=%d", task_id[:8], result.rows_loaded, result.batch_count)
        except Exception as e:
            _tasks[task_id].status = "failed"
            _tasks[task_id].error = str(e)
            await update_migration(task_id, "failed", error=str(e), stage="transformed")
            logger.error("Task %s: transform failed: %s", task_id[:8], e)

    asyncio.create_task(_execute())
    return task_id


async def run_publish(
    connection_id: str,
    table_name: str,
    merge_keys: list[str] | None,
    target_config: dict[str, Any],
    connection_name: str | None = None,
    persist_merge_keys: bool = True,
) -> str:
    """Stage 3: curated/_staging -> curated/ via publish_curated(), with the
    create/append/upsert branch decided once up front from dataset_exists()."""
    task_id = str(uuid.uuid4())
    _tasks[task_id] = TaskEntry(status="running", stage="published")
    logger.info("Task %s: publish started connection=%s table=%s", task_id[:8], connection_id[:8], table_name)

    await save_migration(task_id, connection_id, connection_name, "s3", "s3", [table_name], stage="published")
    if persist_merge_keys:
        await save_merge_keys(connection_id, merge_keys or [])

    async def _execute():
        try:
            result = await publish_curated(
                connection_id=connection_id,
                table_name=table_name,
                merge_keys=merge_keys,
                target_kwargs=target_config,
            )
            load_result = LoadResult(
                destination_type="s3",
                table_name=result.table_name,
                rows_loaded=result.rows_loaded,
                batch_count=result.batch_count,
                errors=result.errors,
            )
            _tasks[task_id].status = "completed"
            _tasks[task_id].result = [load_result]
            _tasks[task_id].detail = {"action": result.action, "schema_changed": result.schema_changed}
            await update_migration(task_id, "completed", result=json.dumps([_load_result_dict(load_result)]), stage="published")
            logger.info("Task %s: publish completed: action=%s rows=%d", task_id[:8], result.action, result.rows_loaded)
        except Exception as e:
            _tasks[task_id].status = "failed"
            _tasks[task_id].error = str(e)
            await update_migration(task_id, "failed", error=str(e), stage="published")
            logger.error("Task %s: publish failed: %s", task_id[:8], e)

    asyncio.create_task(_execute())
    return task_id
