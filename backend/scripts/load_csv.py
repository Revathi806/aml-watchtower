"""Load a CSV matching the SAML-D column names into the normalized core tables.
Use only a legally obtained dataset copy. Defaults to a 200k-row sample if --limit is supplied.
"""
import argparse, asyncio, csv
from datetime import datetime
from pathlib import Path
import asyncpg
from app.config import settings

ALIASES = {
 'time':['Time','time'], 'date':['Date','date'], 'sender':['Sender_account','sender_account','sender'],
 'receiver':['Receiver_account','receiver_account','receiver'], 'amount':['Amount','amount'],
 'pcurrency':['Payment_currency','payment_currency'], 'rcurrency':['Received_currency','received_currency'],
 'sender_bank':['Sender_bank_location','sender_bank_location'], 'receiver_bank':['Receiver_bank_location','receiver_bank_location'],
 'ptype':['Payment_type','payment_type'], 'label':['Is_laundering','is_laundering'], 'typology':['Laundering_type','laundering_type']}

def pick(row, key):
    for k in ALIASES[key]:
        if k in row: return row[k]
    return None

def parse_time(row):
    value = f"{pick(row,'date') or ''} {pick(row,'time') or ''}".strip()
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.fromisoformat(value) if fmt is None else datetime.strptime(value,fmt)
            return dt
        except Exception: pass
    raise ValueError(f"Unrecognized timestamp: {value}")

async def main(path, limit):
    if not settings.database_url: raise SystemExit("Set DATABASE_URL in .env first")
    conn=await asyncpg.connect(settings.database_url,ssl="require")
    try:
        bank_cache={}; customer_cache={}; account_cache=set(); typ_cache={r['typology_name']:r['typology_id'] for r in await conn.fetch('SELECT typology_id,typology_name FROM core.laundering_typology')}
        inserted=0
        with open(path,newline='',encoding='utf-8-sig') as f:
            reader=csv.DictReader(f)
            async with conn.transaction():
                for i,row in enumerate(reader):
                    if limit and i>=limit: break
                    sender=str(pick(row,'sender') or '').strip(); receiver=str(pick(row,'receiver') or '').strip()
                    if not sender or not receiver: continue
                    try: event_time=parse_time(row); amount=float(pick(row,'amount') or 0)
                    except (ValueError,TypeError): continue
                    if amount < 0: continue
                    sender_bank=str(pick(row,'sender_bank') or 'Unknown'); receiver_bank=str(pick(row,'receiver_bank') or 'Unknown')
                    for bank_name,loc in [(sender_bank,sender_bank),(receiver_bank,receiver_bank)]:
                        if (bank_name,loc) not in bank_cache:
                            bank_cache[(bank_name,loc)]=await conn.fetchval('INSERT INTO core.bank(bank_name,bank_location) VALUES($1,$2) ON CONFLICT(bank_name,bank_location) DO UPDATE SET bank_name=EXCLUDED.bank_name RETURNING bank_id',bank_name,loc)
                    for acct,loc in [(sender,sender_bank),(receiver,receiver_bank)]:
                        if acct not in account_cache:
                            cust=await conn.fetchval('INSERT INTO core.customer(customer_ref,risk_rating) VALUES($1,$2) ON CONFLICT(customer_ref) DO UPDATE SET customer_ref=EXCLUDED.customer_ref RETURNING customer_id',f'cust_{acct}','Unknown')
                            await conn.execute('INSERT INTO core.account(account_id,customer_id,bank_id) VALUES($1,$2,$3) ON CONFLICT(account_id) DO NOTHING',acct,cust,bank_cache[(loc,loc)])
                            account_cache.add(acct)
                    typ=str(pick(row,'typology') or 'legitimate').strip().lower()
                    typ_id=typ_cache.get(typ)
                    if typ_id is None:
                        typ_id=await conn.fetchval('INSERT INTO core.laundering_typology(typology_name,is_suspicious) VALUES($1,$2) ON CONFLICT(typology_name) DO UPDATE SET typology_name=EXCLUDED.typology_name RETURNING typology_id',typ,typ not in ('legitimate','none',''))
                        typ_cache[typ]=typ_id
                    label=str(pick(row,'label') or '').strip().lower() in ('1','true','yes')
                    # Labels are stored for evaluation only; detection rules never read this field.
                    txid=i+1
                    await conn.execute('''INSERT INTO core.transaction(transaction_id,event_time,amount,payment_currency,received_currency,payment_type,sender_bank_location,receiver_bank_location,source_label,typology_id)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(transaction_id) DO NOTHING''',txid,event_time,amount,pick(row,'pcurrency'),pick(row,'rcurrency'),pick(row,'ptype'),sender_bank,receiver_bank,label,typ_id)
                    await conn.execute('INSERT INTO core.transaction_acc_id(transaction_id,sender_account_id,receiver_account_id) VALUES($1,$2,$3) ON CONFLICT(transaction_id) DO NOTHING',txid,sender,receiver)
                    inserted+=1
        print(f"Loaded/verified {inserted} rows from {path}. Verify counts in core.transaction before detection.")
    finally: await conn.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('csv'); p.add_argument('--limit',type=int,default=200000); a=p.parse_args(); asyncio.run(main(a.csv,a.limit))
