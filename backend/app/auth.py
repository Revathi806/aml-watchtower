from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import settings
from .db import get_pool

password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try: return password_hash.verify(password, hashed)
    except Exception: return False

def make_token(email: str, role: str) -> str:
    return jwt.encode({"sub": email, "role": role, "exp": datetime.now(timezone.utc) + timedelta(hours=8)}, settings.jwt_secret, algorithm="HS256")

async def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials: raise HTTPException(401, "Bearer token required")
    try: payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError: raise HTTPException(401, "Invalid or expired token")
    email = payload.get("sub")
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "SELECT email, role, active FROM core.analyst WHERE lower(email)=lower($1)",
            email
        )
    if not record or not record["active"]:
        raise HTTPException(401, "User account is inactive or no longer exists")
    # Read the current role from the database so role changes take effect immediately.
    return {"email": record["email"], "role": record["role"]}

def require_admin(user=Depends(current_user)):
    if user["role"] != "admin": raise HTTPException(403, "Administrator role required")
    return user
