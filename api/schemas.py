from pydantic import BaseModel, Field
from typing import Any


class MigrationRequest(BaseModel):
    source: str = Field(description="Source type name (e.g. postgresql, file_upload, mongodb, sql)")
    target: str = Field(description="Target type name (e.g. s3)")
    tables: list[str] = Field(description="List of table/collection names to migrate")
    source_config: dict[str, Any] = Field(default_factory=dict, description="Config kwargs passed to the source connector")
    target_config: dict[str, Any] = Field(default_factory=dict, description="Config kwargs passed to the target connector")


class MigrationResponse(BaseModel):
    task_id: str
    status: str
    message: str


class LoadResultSchema(BaseModel):
    destination_type: str
    table_name: str
    rows_loaded: int
    batch_count: int
    errors: list[str]


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    stage: str = "landed"
    result: list[LoadResultSchema] | None = None
    error: str | None = None
    detail: dict[str, Any] | None = None


class ConnectionCreate(BaseModel):
    name: str
    source_type: str
    description: str = ""

    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None

    ssl_mode: str | None = None
    ssl_cert: str | None = None
    ssl_key: str | None = None
    ssl_root_cert: str | None = None
    pool_min_size: int = 2
    pool_max_size: int = 10

    connection_string: str | None = None
    max_pool_size: int = 10

    dialect: str | None = None
    driver: str | None = None
    extra_params: dict[str, str] | None = None
    pool_size: int = 5
    max_overflow: int = 10

    input_dir: str | None = None
    file_pattern: str = "*"
    recursive: bool = False
    include_content: bool = False
    files: list[str] | None = None

    batch_size: int = 20_000
    incremental_column: str | None = None
    incremental_field: str | None = None
    cursor_name: str | None = None
    checkpoint_file: str | None = None
    pool_timeout: float = 30.0

    region: str | None = None
    catalog: str | None = None
    workgroup: str | None = None
    output_location: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    session_token: str | None = None


class ConnectionResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    source_type: str
    config: dict
    created_at: str | None = None


class ConnectionTestResponse(BaseModel):
    status: str
    message: str


class ConnectionListResponse(BaseModel):
    connections: list[ConnectionResponse]


class TableListResponse(BaseModel):
    tables: list[str]


class DatabaseListResponse(BaseModel):
    databases: list[str]


class ConnectionMigrateRequest(BaseModel):
    tables: list[str]
    target_config: dict


class TransformRuleConfig(BaseModel):
    rename: dict[str, str] = Field(default_factory=dict)
    cast: dict[str, str] = Field(default_factory=dict)
    drop_columns: list[str] = Field(default_factory=list)
    drop_nulls: list[str] = Field(default_factory=list)
    dedupe_keys: list[str] | None = None


class TransformRequest(BaseModel):
    table_name: str
    sql: str | None = Field(default=None, description="Manual transform: SQL run against Athena over the raw zone")
    rule: TransformRuleConfig | None = Field(default=None, description="Automatic transform: declarative column rules, works with either reader")
    source_type: str = Field(default="athena", description="'athena' (required for sql transforms) or 's3' (direct reader fallback)")
    source_config: dict[str, Any] = Field(default_factory=dict)
    target_config: dict[str, Any] = Field(default_factory=dict)
    batch_size: int | None = None


class PublishRequest(BaseModel):
    table_name: str
    merge_keys: list[str] | None = Field(default=None, description="Row key(s) to upsert on; omit for a plain append")
    target_config: dict[str, Any] = Field(default_factory=dict)


class PublishResultSchema(BaseModel):
    table_name: str
    action: str
    schema_changed: bool
    rows_loaded: int
    batch_count: int
    errors: list[str]


class QueryRequest(BaseModel):
    sql: str = Field(description="SQL query text to execute against the connection's source")


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int


class UserCreate(BaseModel):
    email: str
    password: str
    name: str


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class HealthResponse(BaseModel):
    status: str = "ok"


class SourcesResponse(BaseModel):
    sources: list[str]


class TargetsResponse(BaseModel):
    targets: list[str]
