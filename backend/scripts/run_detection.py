"""Run SQL-backed batch detection and write idempotent alerts."""
import asyncio, json
from app.config import settings
import asyncpg
from app.detection import detect, DEFAULT_RULES

async def main():
    if not settings.database_url: raise SystemExit('Set DATABASE_URL in .env')
    conn=await asyncpg.connect(settings.database_url,ssl='require')
    try:
        configs=await conn.fetch('SELECT rule_name,enabled,weight,threshold FROM core.rule_config')
        rules={r['rule_name']:{'enabled':r['enabled'],'weight':r['weight'],'threshold':dict(r['threshold'])} for r in configs}
        rows=await conn.fetch('''SELECT t.transaction_id,t.event_time AS timestamp,t.amount,t.payment_type,e.sender_account_id AS sender_account,
          e.receiver_account_id AS receiver_account,t.sender_bank_location,t.receiver_bank_location
          FROM core.transaction t JOIN core.transaction_acc_id e USING(transaction_id) ORDER BY t.event_time LIMIT 200000''')
        alerts=detect([dict(r) for r in rows],rules)
        async with conn.transaction():
            for a in alerts:
                await conn.execute('''INSERT INTO core.alert(transaction_id,risk_score,matched_rules) VALUES($1,$2,$3)
                ON CONFLICT(transaction_id) DO UPDATE SET risk_score=GREATEST(core.alert.risk_score,EXCLUDED.risk_score),
                matched_rules=(SELECT ARRAY(SELECT DISTINCT unnest(core.alert.matched_rules || EXCLUDED.matched_rules)))''',a['transaction_id'],a['risk_score'],a['matched_rules'])
                for rule in a['matched_rules']:
                    await conn.execute('INSERT INTO core.detected_rule(transaction_id,rule_name) VALUES($1,$2) ON CONFLICT DO NOTHING',a['transaction_id'],rule)
        print(f'Detection completed. {len(alerts)} candidate alerts inserted or updated.')
    finally: await conn.close()

if __name__=='__main__': asyncio.run(main())
