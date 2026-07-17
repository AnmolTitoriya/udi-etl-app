import asyncio
import os
import platform
from dotenv import load_dotenv

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()
from udi_connectors import migrate_all


async def setup_table():
    import psycopg
    conn_str = (
        f"host={os.getenv('PG_HOST')} port={os.getenv('PG_PORT')} "
        f"dbname={os.getenv('PG_DATABASE')} user={os.getenv('PG_USERNAME')} "
        f"password={os.getenv('PG_PASSWORD')} sslmode={os.getenv('PG_SSLMODE', 'prefer')}"
    )
    async with await psycopg.AsyncConnection.connect(conn_str) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS test_users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT
            )
        """)
        await conn.execute("DELETE FROM test_users")
        async with conn.cursor() as cur:
            for i in range(50):
                await cur.execute(
                    "INSERT INTO test_users (name, email) VALUES (%s, %s)",
                    (f"user_{i}", f"user_{i}@test.com"),
                )
        await conn.commit()
    print("Table test_users created and seeded with 50 rows.")


async def main():
    await setup_table()

    results = await migrate_all(
        source_name="postgresql",
        target_name="s3",
        tables=["test_users"],
        source_kwargs={
            "host": os.getenv("PG_HOST"),
            "port": int(os.getenv("PG_PORT", "5432")),
            "database": os.getenv("PG_DATABASE"),
            "username": os.getenv("PG_USERNAME"),
            "password": os.getenv("PG_PASSWORD"),
            "ssl_mode": os.getenv("PG_SSLMODE", "prefer"),
        },
        target_kwargs={
            "bucket_name": os.getenv("S3_BUCKET"),
            "region": os.getenv("AWS_REGION", "us-east-1"),
            "file_format": "csv",
            "compression": "none",
        },
    )
    for r in results:
        print(f"Table {r.table_name}: {r.rows_loaded} rows in {r.batch_count} files")
        if r.errors:
            print(f"  Errors: {r.errors}")
        else:
            print(f"  OK")


asyncio.run(main())
