"""Refresh dashboard materialized views after loading data or running detection."""
import asyncio
import asyncpg
from app.config import settings

async def main():
    if not settings.database_url:
        raise SystemExit("Set DATABASE_URL in .env first")
    conn = await asyncpg.connect(settings.database_url, ssl="require")
    try:
        for view in ("analytics.kpi_daily", "analytics.typology_daily", "analytics.geo_flagged"):
            await conn.execute(f"REFRESH MATERIALIZED VIEW {view}")
        print("Refreshed analytics.kpi_daily, analytics.typology_daily, analytics.geo_flagged")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
