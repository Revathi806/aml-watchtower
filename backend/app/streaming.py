"""Replay historical transactions to Kafka or consume them with Redis-backed window rules.

Run inside the API container:
  python -m app.streaming producer
  python -m app.streaming consumer
This is an educational replay pipeline, not a live bank feed.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

import asyncpg
import psycopg
from kafka import KafkaConsumer, KafkaProducer
from redis import Redis

from .config import settings


def _timestamp(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def load_events():
    conn = await asyncpg.connect(settings.database_url, ssl="require")
    try:
        rows = await conn.fetch(
            """SELECT t.transaction_id,t.event_time,t.amount,t.payment_currency,t.payment_type,
                      t.sender_bank_location,t.receiver_bank_location,
                      e.sender_account_id,e.receiver_account_id
               FROM core.transaction t JOIN core.transaction_acc_id e USING(transaction_id)
               ORDER BY t.event_time,t.transaction_id LIMIT 20000"""
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


def produce():
    if not settings.database_url:
        raise SystemExit("Set DATABASE_URL in .env first")
    events = asyncio.run(load_events())
    producer = KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        value_serializer=lambda item: json.dumps(item, default=str).encode("utf-8"),
        key_serializer=lambda item: item.encode("utf-8"),
        retries=5,
    )
    try:
        for event in events:
            producer.send("transactions", key=str(event["sender_account_id"]), value=event)
        producer.flush()
    finally:
        producer.close()
    print(f"Published {len(events)} historical transactions to Kafka topic 'transactions'.")


def consume():
    if not settings.database_url:
        raise SystemExit("Set DATABASE_URL in .env first")
    consumer = KafkaConsumer(
        "transactions",
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        value_deserializer=lambda item: json.loads(item.decode("utf-8")),
        group_id="aml-watchtower-demo",
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        consumer_timeout_ms=1000,
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    db = psycopg.connect(settings.database_url, sslmode="require")
    processed = 0
    try:
        for message in consumer:
            event = message.value
            event_time = _timestamp(event["event_time"])
            epoch = event_time.timestamp()
            amount = float(event.get("amount") or 0)
            txid = int(event["transaction_id"])
            sender = str(event["sender_account_id"])
            receiver = str(event["receiver_account_id"])
            matched = []

            # Structuring: at least three just-under-threshold payments from the same sender in 24h.
            sender_key = f"aml:sender:{sender}"
            if 800 <= amount < 1000:
                redis.zadd(sender_key, {str(txid): epoch})
                redis.zremrangebyscore(sender_key, "-inf", epoch - 86400)
                redis.expire(sender_key, 172800)
                if redis.zcount(sender_key, epoch - 86400, epoch) >= 3:
                    matched.append("structuring")

            # Fan-out: unique receivers from this sender in a 24h event-time window.
            fanout_key = f"aml:fanout:{sender}"
            redis.zadd(fanout_key, {receiver: epoch})
            redis.zremrangebyscore(fanout_key, "-inf", epoch - 86400)
            redis.expire(fanout_key, 172800)
            if redis.zcount(fanout_key, epoch - 86400, epoch) >= 4:
                matched.append("fan_out")

            # Fan-in: unique senders into this receiver in a 24h event-time window.
            fanin_key = f"aml:fanin:{receiver}"
            redis.zadd(fanin_key, {sender: epoch})
            redis.zremrangebyscore(fanin_key, "-inf", epoch - 86400)
            redis.expire(fanin_key, 172800)
            if redis.zcount(fanin_key, epoch - 86400, epoch) >= 4:
                matched.append("fan_in")

            if matched:
                with db.cursor() as cur:
                    cur.execute(
                        "SELECT rule_name,weight FROM core.rule_config WHERE enabled=true AND rule_name = ANY(%s)",
                        (matched,),
                    )
                    weight_map = {row[0]: row[1] for row in cur.fetchall()}
                    matched = [rule for rule in matched if rule in weight_map]
                    score = min(100, sum(weight_map[rule] for rule in matched))
                    if score >= 30:
                        cur.execute(
                            """INSERT INTO core.alert(transaction_id,risk_score,matched_rules)
                               VALUES(%s,%s,%s) ON CONFLICT(transaction_id) DO UPDATE SET
                               risk_score=GREATEST(core.alert.risk_score,EXCLUDED.risk_score),
                               matched_rules=(SELECT ARRAY(SELECT DISTINCT unnest(core.alert.matched_rules || EXCLUDED.matched_rules)))""",
                            (txid, score, matched),
                        )
                        for rule in matched:
                            cur.execute(
                                "INSERT INTO core.detected_rule(transaction_id,rule_name) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                                (txid, rule),
                            )
                db.commit()
            processed += 1
            if processed % 1000 == 0:
                print(f"Processed {processed} Kafka events", flush=True)
        print(f"Consumer finished after {processed} events. Restart producer to replay more data.")
    finally:
        consumer.close()
        redis.close()
        db.close()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "producer"
    if mode == "producer":
        produce()
    elif mode == "consumer":
        consume()
    else:
        raise SystemExit("Usage: python -m app.streaming [producer|consumer]")


if __name__ == "__main__":
    main()
