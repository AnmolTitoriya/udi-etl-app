import asyncio
import logging
import os
import platform

import psycopg
from dotenv import load_dotenv

load_dotenv()

METADATA_URL = os.getenv("METADATA_DATABASE_URL", "postgresql://postgres:123456789@localhost:5432/data_migration_meta")

# Use same credentials to connect to default 'postgres' DB for creating the metadata DB
BASE_URL = METADATA_URL.rsplit("/", 1)[0] + "/postgres"


async def seed():
    # Step 1: Create data_migration_meta database if it doesn't exist
    conn = await psycopg.AsyncConnection.connect(BASE_URL)
    await conn.set_autocommit(True)
    try:
        rows = await conn.execute("SELECT 1 FROM pg_database WHERE datname = 'data_migration_meta'")
        exists = await rows.fetchone()
        if not exists:
            await conn.execute("CREATE DATABASE data_migration_meta")
            print("Created database: data_migration_meta")
        else:
            print("Database already exists: data_migration_meta")
    finally:
        await conn.close()

    # Step 2: Create users, connections, and migrations tables
    conn = await psycopg.AsyncConnection.connect(METADATA_URL)
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
            import hashlib, uuid, os
            salt = os.urandom(32)
            key = hashlib.pbkdf2_hmac("sha256", "demo123".encode(), salt, 100_000)
            hashed = salt.hex() + ":" + key.hex()
            await conn.execute(
                "INSERT INTO users (id, email, password, name) VALUES (%s, %s, %s, %s)",
                (str(uuid.uuid4()), "demo@example.com", hashed, "Demo User"),
            )
            await conn.commit()
            print("Seeded demo user: demo@example.com / demo123")
        else:
            print("Users table already populated, skipping seed")

        print("Created tables: users, connections, migrations")
    finally:
        await conn.close()

    # Step 3: Create demo_source database with fake users table
    conn = await psycopg.AsyncConnection.connect(BASE_URL)
    await conn.set_autocommit(True)
    try:
        rows = await conn.execute("SELECT 1 FROM pg_database WHERE datname = 'demo_source'")
        exists = await rows.fetchone()
        if not exists:
            await conn.execute("CREATE DATABASE demo_source")
            print("Created database: demo_source")
        else:
            print("Database already exists: demo_source")
    finally:
        await conn.close()

    DEMO_URL = METADATA_URL.rsplit("/", 1)[0] + "/demo_source"
    conn = await psycopg.AsyncConnection.connect(DEMO_URL)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        rows = await conn.execute("SELECT COUNT(*) FROM users")
        count = (await rows.fetchone())[0]
        if count == 0:
            await conn.execute("""
                INSERT INTO users (name, email) VALUES
                    ('Alice Johnson', 'alice@demo.com'),
                    ('Bob Smith', 'bob@demo.com'),
                    ('Charlie Brown', 'charlie@demo.com'),
                    ('Diana Prince', 'diana@demo.com')
            """)
            print("Inserted 4 dummy users into demo_source.users")
        else:
            print(f"users table already has {count} rows, skipping insert")
        await conn.commit()
    finally:
        await conn.close()

    print("\nMetadata database ready!")
    print(f"  Database: data_migration_meta -> Table: connections")
    print(f"  Database: demo_source        -> Table: users (4 dummy rows)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed())
