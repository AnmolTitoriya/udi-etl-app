"""Example custom source connector, loaded via UDI_CONNECTOR_PLUGINS_DIR.

Demonstrates that a connector living outside udi-connectors' own package
registers and flows through create_source()/migrate_all() identically to a
built-in one — it self-registers via @Source(...) on import, same as
postgresql/mongodb/sql/etc. Generates synthetic rows; no external
dependency or network access required, so it's usable as a source with
nothing else running.
"""

import asyncio
import random
from collections.abc import AsyncIterator
from typing import Literal

import pyarrow as pa
from udi_connectors._registry import Source
from udi_packages import Batch, BatchMetadata, ConnectorError, ExtractResult
from udi_packages.config import BaseConfig


class RandomNumbersConfig(BaseConfig):
    source_type: Literal["random_numbers"] = "random_numbers"
    row_count: int = 1000
    batch_size: int = 200
    seed: int | None = None


@Source("random_numbers")
class RandomNumbersConnector:
    Config = RandomNumbersConfig

    def __init__(self):
        self._config: RandomNumbersConfig | None = None

    async def connect(self, config: RandomNumbersConfig) -> None:
        self._config = config

    async def disconnect(self) -> None:
        self._config = None

    async def test_connection(self) -> bool:
        return self._config is not None

    async def list_tables(self, config: RandomNumbersConfig) -> list[str]:
        return ["numbers"]

    async def list_databases(self, config: RandomNumbersConfig) -> list[str]:
        return ["synthetic"]

    async def get_schema(self, table_name: str = "numbers") -> pa.Schema:
        return pa.schema([pa.field("id", pa.int64()), pa.field("value", pa.float64())])

    async def get_checkpoint(self, table_name: str) -> dict | None:
        return None

    def supports_incremental(self) -> bool:
        return False

    async def extract(
        self,
        table_name: str,
        config: RandomNumbersConfig,
        columns: list[str] | None = None,
        filter_predicate: str | None = None,
    ) -> ExtractResult:
        cfg = config or self._config
        if not cfg:
            raise ConnectorError("RandomNumbersConnector is not connected", "random_numbers", retryable=False)
        rng = random.Random(cfg.seed)

        async def batch_generator() -> AsyncIterator[Batch]:
            produced = 0
            batch_num = 0
            while produced < cfg.row_count:
                n = min(cfg.batch_size, cfg.row_count - produced)
                table = pa.table({
                    "id": list(range(produced, produced + n)),
                    "value": [rng.random() * 100 for _ in range(n)],
                })
                yield Batch(
                    data=table,
                    metadata=BatchMetadata(
                        source_name="random_numbers",
                        table_name=table_name,
                        batch_id=f"{table_name}_{batch_num}",
                        row_count=n,
                        byte_size=table.nbytes,
                        schema=table.schema,
                    ),
                )
                produced += n
                batch_num += 1
                await asyncio.sleep(0)

        return ExtractResult(batches=batch_generator())
