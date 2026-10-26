import asyncio
import asyncpg
from app.config import settings

async def main():
    conn = None
    try:
        conn = await asyncpg.connect(
            settings.database_url,
            ssl="require",
            timeout=20
        )
        print("Connected to database")
        result = await conn.fetchval("SELECT 1")
        print("Query result:", result)
    except Exception as e:
        print("Connection failed:", type(e).__name__, str(e))
    finally:
        if conn is not None and not conn.is_closed():
            await conn.close()

asyncio.run(main())