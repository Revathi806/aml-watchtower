import asyncio
from pathlib import Path
import asyncpg
from app.config import settings

async def main():
    if not settings.database_url:
        raise SystemExit("Set DATABASE_URL in .env first")
    sql = Path(__file__).resolve().parents[1].joinpath("sql", "schema.sql").read_text()
    conn = await asyncpg.connect(settings.database_url, ssl="require")
    try:
        await conn.execute(sql)
        await conn.execute("""INSERT INTO core.analyst(email,display_name,role) VALUES
        ($1,'Demo Analyst','analyst'),($2,'Demo Administrator','admin') ON CONFLICT(email) DO NOTHING""", settings.demo_analyst_email, settings.demo_admin_email)
        print("Database schema and default rules created.")
    finally: await conn.close()

if __name__ == '__main__': asyncio.run(main())
