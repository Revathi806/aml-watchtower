from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import get_pool, close_pool
from .auth import current_user, require_admin, make_token, verify_password, hash_password
from .schemas import LoginRequest, AlertUpdate, RuleUpdate, UserCreate

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_pool()

app = FastAPI(title="AML Transaction Monitoring Platform", version="1.0.0", lifespan=lifespan,
              description="Academic prototype for transparent, rule-based AML transaction monitoring.")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    return {"status":"ok", "service":"aml-api", "database_configured": bool(settings.database_url)}

@app.post("/auth/login")
async def login(body: LoginRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "SELECT email, role, password_hash, active FROM core.analyst WHERE lower(email)=lower($1)",
            body.email.strip()
        )
    if record and record["active"] and record["password_hash"] and verify_password(body.password, record["password_hash"]):
        email, role = record["email"], record["role"]
    # Keep environment-configured demo accounts available for initial setup.
    elif (not record or (record["active"] and not record["password_hash"])) and body.email == settings.demo_admin_email and body.password == settings.demo_admin_password:
        email, role = settings.demo_admin_email, "admin"
    elif (not record or (record["active"] and not record["password_hash"])) and body.email == settings.demo_analyst_email and body.password == settings.demo_analyst_password:
        email, role = settings.demo_analyst_email, "analyst"
    else:
        raise HTTPException(401, "Invalid email/password or inactive account")
    return {"access_token": make_token(email, role), "token_type":"bearer", "user":{"email":email,"role":role}}

@app.get("/me")
async def me(user=Depends(current_user)): return user

@app.get("/alerts")
async def list_alerts(status: str | None = None, min_score: int = Query(0, ge=0, le=100), limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), user=Depends(current_user)):
    pool = await get_pool()
    sql = """SELECT a.alert_id,a.transaction_id,a.risk_score,a.matched_rules,a.status,a.created_at,a.updated_at,
                     a.assigned_to,t.event_time,t.amount,t.payment_currency,t.payment_type,e.sender_account_id,e.receiver_account_id,
                     t.sender_bank_location,t.receiver_bank_location
              FROM core.alert a JOIN core.transaction t USING(transaction_id)
              LEFT JOIN core.transaction_acc_id e USING(transaction_id)
              WHERE a.risk_score >= $1 AND ($2::text IS NULL OR a.status=$2)
                AND ($5::boolean OR a.assigned_to=(SELECT analyst_id FROM core.analyst WHERE lower(email)=lower($6)))
              ORDER BY a.risk_score DESC,a.created_at DESC LIMIT $3 OFFSET $4"""
    is_admin = user["role"] == "admin"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, min_score, status, limit, offset, is_admin, user["email"])
        total = await conn.fetchval("SELECT count(*) FROM core.alert a WHERE a.risk_score >= $1 AND ($2::text IS NULL OR a.status=$2) AND ($3::boolean OR a.assigned_to=(SELECT analyst_id FROM core.analyst WHERE lower(email)=lower($4)))", min_score, status, is_admin, user["email"])
    return {"items":[dict(r) for r in rows], "total":total, "limit":limit, "offset":offset}

@app.get("/alerts/{alert_id}")
async def get_alert(alert_id: int, user=Depends(current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""SELECT a.*,t.event_time,t.amount,t.payment_currency,t.received_currency,t.payment_type,
          t.sender_bank_location,t.receiver_bank_location,e.sender_account_id,e.receiver_account_id
          FROM core.alert a JOIN core.transaction t USING(transaction_id) LEFT JOIN core.transaction_acc_id e USING(transaction_id)
          WHERE a.alert_id=$1 AND ($2::boolean OR a.assigned_to=(SELECT analyst_id FROM core.analyst WHERE lower(email)=lower($3)))""", alert_id, user["role"] == "admin", user["email"])
        if not row: raise HTTPException(404,"Alert not found or not assigned to you")
        notes = await conn.fetch("SELECT n.note_id,n.note,n.created_at,an.email FROM core.alert_note n LEFT JOIN core.analyst an USING(analyst_id) WHERE n.alert_id=$1 ORDER BY n.created_at", alert_id)
        audit = await conn.fetch("SELECT old_status,new_status,changed_by,changed_at,details FROM core.alert_audit WHERE alert_id=$1 ORDER BY changed_at DESC LIMIT 50", alert_id)
    result = dict(row); result["notes"]=[dict(x) for x in notes]; result["audit"]=[dict(x) for x in audit]
    return result

@app.patch("/alerts/{alert_id}")
async def update_alert(alert_id: int, body: AlertUpdate, user=Depends(current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT alert_id,status,assigned_to FROM core.alert WHERE alert_id=$1 FOR UPDATE", alert_id)
            if not row: raise HTTPException(404,"Alert not found")
            analyst_id = await conn.fetchval("SELECT analyst_id FROM core.analyst WHERE lower(email)=lower($1) AND active=true", user["email"])
            if user["role"] != "admin" and (not analyst_id or row["assigned_to"] != analyst_id):
                raise HTTPException(403,"You can only update alerts assigned to you")
            if body.assigned_to and user["role"] != "admin": raise HTTPException(403,"Only admins may assign alerts")
            assigned_id = row.get("assigned_to") if hasattr(row,"get") else None
            if body.assigned_to:
                assigned_id = await conn.fetchval("SELECT analyst_id FROM core.analyst WHERE email=$1 AND active=true", body.assigned_to)
                if not assigned_id: raise HTTPException(400,"Active analyst email not found")
            await conn.execute("SELECT set_config('app.user_email',$1,true)", user["email"])
            await conn.execute("UPDATE core.alert SET status=$2, assigned_to=COALESCE($3,assigned_to), updated_at=now() WHERE alert_id=$1", alert_id, body.status, assigned_id)
            if body.note:
                await conn.execute("INSERT INTO core.alert_note(alert_id,analyst_id,note) VALUES($1,$2,$3)", alert_id, analyst_id, body.note)
    return {"message":"Alert updated", "alert_id":alert_id, "status":body.status}

@app.get("/analytics/kpis")
async def analytics_kpis(user=Depends(current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        data = await conn.fetchrow("""SELECT (SELECT count(*) FROM core.transaction) AS transactions,
          (SELECT count(*) FROM core.alert) AS alerts,
          (SELECT count(*) FROM core.alert WHERE status='Open') AS open_alerts,
          (SELECT count(*) FROM core.alert WHERE status='Escalated') AS escalated_alerts,
          (SELECT COALESCE(round(avg(risk_score)::numeric,1),0) FROM core.alert) AS avg_risk""")
        timeseries = await conn.fetch("SELECT day,transaction_count,flagged_count,open_alert_count FROM analytics.kpi_daily ORDER BY day DESC LIMIT 30")
        typologies = await conn.fetch("SELECT typology,sum(alert_count)::int AS count FROM analytics.typology_daily GROUP BY typology ORDER BY count DESC")
        geo = await conn.fetch("SELECT bank_location,flagged_count FROM analytics.geo_flagged ORDER BY flagged_count DESC LIMIT 10")
    return {"kpis":dict(data), "timeseries":[dict(x) for x in reversed(timeseries)], "typologies":[dict(x) for x in typologies], "geo":[dict(x) for x in geo]}

@app.get("/search")
async def search(q: str = Query(min_length=1,max_length=100), limit: int = Query(50,ge=1,le=200), user=Depends(current_user)):
    pool = await get_pool(); pattern = f"%{q}%"
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT a.alert_id,a.transaction_id,a.risk_score,a.status,a.matched_rules,t.amount,t.event_time,e.sender_account_id,e.receiver_account_id
        FROM core.alert a JOIN core.transaction t USING(transaction_id) LEFT JOIN core.transaction_acc_id e USING(transaction_id)
        WHERE (e.sender_account_id ILIKE $1 OR e.receiver_account_id ILIKE $1 OR a.transaction_id::text ILIKE $1 OR t.payment_type ILIKE $1)
          AND ($3::boolean OR a.assigned_to=(SELECT analyst_id FROM core.analyst WHERE lower(email)=lower($4)))
        ORDER BY a.risk_score DESC LIMIT $2""", pattern, limit, user["role"] == "admin", user["email"])
    return {"items":[dict(r) for r in rows]}

@app.get("/rules")
async def list_rules(user=Depends(current_user)):
    pool=await get_pool()
    async with pool.acquire() as conn: rows=await conn.fetch("SELECT rule_name,enabled,weight,threshold,updated_at FROM core.rule_config ORDER BY rule_name")
    return {"items":[dict(r) for r in rows]}

@app.put("/rules/{rule_name}")
async def update_rule(rule_name: str, body: RuleUpdate, user=Depends(require_admin)):
    pool=await get_pool()
    async with pool.acquire() as conn:
        row=await conn.fetchrow("UPDATE core.rule_config SET enabled=$2,weight=$3,threshold=$4::jsonb,updated_at=now() WHERE rule_name=$1 RETURNING rule_name,enabled,weight,threshold,updated_at",rule_name,body.enabled,body.weight,__import__('json').dumps(body.threshold))
    if not row: raise HTTPException(404,"Rule not found")
    return dict(row)

@app.get("/analysts/workload")
async def analyst_workload(user=Depends(require_admin)):
    pool=await get_pool()
    async with pool.acquire() as conn:
        rows=await conn.fetch("""SELECT an.email,an.display_name,an.role,count(a.alert_id) FILTER (WHERE a.status IN ('Open','Assigned'))::int AS active_alerts
        FROM core.analyst an LEFT JOIN core.alert a ON a.assigned_to=an.analyst_id GROUP BY an.analyst_id ORDER BY active_alerts DESC""")
    return {"items":[dict(r) for r in rows]}

@app.get("/admin/users")
async def admin_list_users(user=Depends(require_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT analyst_id,email,display_name,role,active FROM core.analyst ORDER BY role,email")
    return {"items":[dict(r) for r in rows]}

@app.post("/admin/users", status_code=201)
async def admin_create_user(body: UserCreate, user=Depends(require_admin)):
    pool = await get_pool()
    email = body.email.strip().lower()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM core.analyst WHERE lower(email)=lower($1)", email)
        if exists:
            raise HTTPException(409, "A user with this email already exists")
        row = await conn.fetchrow(
            """INSERT INTO core.analyst(email,display_name,role,active,password_hash)
               VALUES($1,$2,$3,true,$4)
               RETURNING analyst_id,email,display_name,role,active""",
            email, body.display_name.strip(), body.role, hash_password(body.password)
        )
    return {"user":dict(row), "message":"User created"}

@app.delete("/admin/users/{analyst_id}")
async def admin_deactivate_user(analyst_id: int, user=Depends(require_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            target = await conn.fetchrow("SELECT analyst_id,email,role,active FROM core.analyst WHERE analyst_id=$1 FOR UPDATE", analyst_id)
            if not target:
                raise HTTPException(404, "User not found")
            if target["email"].lower() == user["email"].lower():
                raise HTTPException(400, "You cannot deactivate your own admin account")
            if not target["active"]:
                return {"message":"User is already inactive"}
            if target["role"] == "admin":
                count = await conn.fetchval("SELECT count(*) FROM core.analyst WHERE role='admin' AND active=true")
                if count <= 1:
                    raise HTTPException(400, "Cannot deactivate the last active administrator")
            await conn.execute("UPDATE core.analyst SET active=false WHERE analyst_id=$1", analyst_id)
    return {"message":"User deactivated; alert and audit history preserved"}

@app.get("/admin/analysts")
async def admin_list_analysts(user=Depends(require_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT analyst_id,email,display_name FROM core.analyst WHERE role='analyst' AND active=true ORDER BY display_name,email")
    return {"items":[dict(r) for r in rows]}

@app.post("/admin/refresh-analytics")
async def refresh_analytics(user=Depends(require_admin)):
    pool=await get_pool()
    async with pool.acquire() as conn:
        for view in ("analytics.kpi_daily","analytics.typology_daily","analytics.geo_flagged"):
            await conn.execute(f"REFRESH MATERIALIZED VIEW {view}")
    return {"message":"Analytics refreshed"}
