import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from udi_connectors import migrate_all
from udi_packages import LoadResult

from .metadata_storage import save_migration, update_migration

logger = logging.getLogger(__name__)


@dataclass
class TaskEntry:
    status: str
    result: list[LoadResult] | None = None
    error: str | None = None


_tasks: dict[str, TaskEntry] = {}


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
                s3_folder=task_id,
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
