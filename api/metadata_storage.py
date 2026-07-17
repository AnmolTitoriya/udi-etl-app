import json
import logging
import os
import uuid
from datetime import datetime, timezone

import psycopg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("METADATA_DATABASE_URL", "postgresql://postgres:123456789@localhost:5432/data_migration_meta")


async def init_db():
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                source_type TEXT NOT NULL,
                config TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            ALTER TABLE connections ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id)
        """)
        await conn.execute("""
            ALTER TABLE connections ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id TEXT PRIMARY KEY,
                connection_id TEXT,
                connection_name TEXT,
                source_type TEXT NOT NULL,
                target_type TEXT NOT NULL,
                tables TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                error TEXT,
                s3_folder TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.commit()

        rows = await conn.execute("SELECT COUNT(*) FROM users")
        count = (await rows.fetchone())[0]
        if count == 0:
            from .auth import hash_password
            user_id = str(uuid.uuid4())
            await conn.execute(
                "INSERT INTO users (id, email, password, name) VALUES (%s, %s, %s, %s)",
                (user_id, "demo@example.com", hash_password("demo123"), "Demo User"),
            )
            await conn.commit()
            logger.info("Seeded demo user: demo@example.com / demo123")

        logger.info("Metadata database initialized: %s", DATABASE_URL)
    finally:
        await conn.close()


async def save_connection(name: str, source_type: str, config: dict, description: str = "", user_id: str = "") -> str:
    conn_id = str(uuid.uuid4())
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO connections (id, user_id, name, description, source_type, config) VALUES (%s, %s, %s, %s, %s, %s)",
            (conn_id, user_id, name, description, source_type, json.dumps(config)),
        )
        await conn.commit()
        logger.info("Saved connection: id=%s name=%s type=%s user=%s", conn_id[:8], name, source_type, user_id[:8])
        return conn_id
    finally:
        await conn.close()


async def list_connections(user_id: str | None = None) -> list[dict]:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        if user_id:
            rows = await conn.execute(
                "SELECT id, name, description, source_type, config, created_at FROM connections WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
        else:
            rows = await conn.execute(
                "SELECT id, name, description, source_type, config, created_at FROM connections ORDER BY created_at DESC"
            )
        results = await rows.fetchall()
        out = []
        for r in results:
            config = json.loads(r[4])
            if "password" in config:
                config["password"] = "****"
            out.append({
                "id": r[0],
                "name": r[1],
                "description": r[2] or "",
                "source_type": r[3],
                "config": config,
                "created_at": r[5].isoformat() if r[5] else None,
            })
        return out
    finally:
        await conn.close()


async def save_migration(
    task_id: str,
    connection_id: str | None,
    connection_name: str | None,
    source_type: str,
    target_type: str,
    tables: list[str],
) -> None:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO migrations (id, connection_id, connection_name, source_type, target_type, tables, status, s3_folder) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (task_id, connection_id, connection_name, source_type, target_type, json.dumps(tables), "running", task_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def update_migration(task_id: str, status: str, result: str | None = None, error: str | None = None) -> None:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE migrations SET status = %s, result = %s, error = %s WHERE id = %s",
            (status, result, error, task_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_connection(conn_id: str) -> dict | None:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        rows = await conn.execute(
            "SELECT id, name, description, source_type, config, created_at FROM connections WHERE id = %s",
            (conn_id,),
        )
        r = await rows.fetchone()
        if not r:
            return None
        config = json.loads(r[4])
        return {
            "id": r[0],
            "name": r[1],
            "description": r[2] or "",
            "source_type": r[3],
            "config": config,
            "created_at": r[5].isoformat() if r[5] else None,
        }
    finally:
        await conn.close()


async def create_user(email: str, password: str, name: str) -> dict:
    user_id = str(uuid.uuid4())
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO users (id, email, password, name) VALUES (%s, %s, %s, %s)",
            (user_id, email, password, name),
        )
        await conn.commit()
        logger.info("Created user: id=%s email=%s", user_id[:8], email)
        return {"id": user_id, "email": email, "name": name}
    except psycopg.errors.UniqueViolation:
        raise ValueError("Email already registered")
    finally:
        await conn.close()


async def get_user_by_email(email: str) -> dict | None:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        rows = await conn.execute("SELECT id, email, password, name FROM users WHERE email = %s", (email,))
        r = await rows.fetchone()
        if not r:
            return None
        return {"id": r[0], "email": r[1], "password": r[2], "name": r[3]}
    finally:
        await conn.close()


async def get_user_by_id(user_id: str) -> dict | None:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        rows = await conn.execute("SELECT id, email, name FROM users WHERE id = %s", (user_id,))
        r = await rows.fetchone()
        if not r:
            return None
        return {"id": r[0], "email": r[1], "name": r[2]}
    finally:
        await conn.close()
