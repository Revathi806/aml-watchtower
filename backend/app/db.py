import asyncpg
from .config import settings

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured. Copy .env.example to .env and set Supabase credentials.")
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5, command_timeout=30, ssl="require")
    return _pool

async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
