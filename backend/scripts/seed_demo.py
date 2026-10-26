"""Insert a small deterministic synthetic dataset for UI/demo smoke tests (not real customer data)."""
import asyncio, random
from datetime import datetime, timedelta, timezone
import asyncpg
from app.config import settings

async def main():
    if not settings.database_url: raise SystemExit('Set DATABASE_URL in .env first')
    random.seed(17); conn=await asyncpg.connect(settings.database_url,ssl='require')
    try:
        banks={}
        for loc in ['London','New York','Singapore','Frankfurt']:
            banks[loc]=await conn.fetchval('INSERT INTO core.bank(bank_name,bank_location) VALUES($1,$2) ON CONFLICT(bank_name,bank_location) DO UPDATE SET bank_name=EXCLUDED.bank_name RETURNING bank_id',f'Demo Bank {loc}',loc)
        accounts=[f'DEMO-{i:04d}' for i in range(1,31)]
        for i,a in enumerate(accounts):
            customer=await conn.fetchval('INSERT INTO core.customer(customer_ref,risk_rating) VALUES($1,$2) ON CONFLICT(customer_ref) DO UPDATE SET customer_ref=EXCLUDED.customer_ref RETURNING customer_id',f'customer-{a}','Medium' if i%7==0 else 'Low')
            await conn.execute('INSERT INTO core.account(account_id,customer_id,bank_id) VALUES($1,$2,$3) ON CONFLICT(account_id) DO NOTHING',a,customer,banks[['London','New York','Singapore','Frankfurt'][i%4]])
        typ_ids={r['typology_name']:r['typology_id'] for r in await conn.fetch('SELECT typology_name,typology_id FROM core.laundering_typology')}
        base=datetime.now(timezone.utc)-timedelta(days=12); txs=[]
        for i in range(1,151):
            sender=accounts[(i*7)%len(accounts)]; receiver=accounts[(i*11+3)%len(accounts)]
            if sender==receiver: receiver=accounts[(accounts.index(receiver)+1)%len(accounts)]
            amount=round(random.uniform(25,700),2); ptype=random.choice(['card payment','bank transfer','wire transfer'])
            # A few intentionally patterned, synthetic examples for rule demonstrations.
            if i in (1,2,3): sender='DEMO-0001'; receiver=accounts[i+5]; amount=950.0; ptype='bank transfer'
            if 10<=i<=14: sender=accounts[i-10]; receiver='DEMO-0020'; amount=round(120+5*i,2)
            if 20<=i<=24: sender='DEMO-0002'; receiver=accounts[i+3]; amount=round(80+2*i,2)
            event_time=base+timedelta(hours=i*2)
            txs.append((i,event_time,amount,'USD','USD',ptype,'London','Singapore',False,typ_ids.get('legitimate')))
            await conn.execute('''INSERT INTO core.transaction(transaction_id,event_time,amount,payment_currency,received_currency,payment_type,sender_bank_location,receiver_bank_location,source_label,typology_id)
              VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(transaction_id) DO NOTHING''',*txs[-1])
            await conn.execute('INSERT INTO core.transaction_acc_id(transaction_id,sender_account_id,receiver_account_id) VALUES($1,$2,$3) ON CONFLICT(transaction_id) DO NOTHING',i,sender,receiver)
        print(f'Inserted or verified {len(txs)} synthetic demo transactions. Run scripts/run_detection.py next.')
    finally: await conn.close()
if __name__=='__main__': asyncio.run(main())
