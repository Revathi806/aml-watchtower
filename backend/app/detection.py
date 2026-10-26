"""Transparent rule-based AML detection. Ground-truth labels are never used as features."""
from collections import defaultdict, deque
from datetime import timedelta

DEFAULT_RULES = {
 "structuring": {"enabled": True, "weight": 40, "threshold": {"min_count": 3, "min_amount": 800, "max_amount": 1000, "window_hours": 24}},
 "fan_in": {"enabled": True, "weight": 30, "threshold": {"min_accounts": 4}},
 "fan_out": {"enabled": True, "weight": 30, "threshold": {"min_accounts": 4}},
 "deposit_send": {"enabled": True, "weight": 35, "threshold": {"ratio": 0.9, "window_hours": 6}},
 "cycle": {"enabled": True, "weight": 50, "threshold": {"max_depth": 4, "max_gap_hours": 24}},
 "behavioural_change": {"enabled": True, "weight": 20, "threshold": {"baseline_multiplier": 3}},
}

def detect(rows, rules=None):
    """rows: iterable dicts with transaction_id, timestamp, sender_account, receiver_account, amount, payment_type, bank locations."""
    rules = rules or DEFAULT_RULES
    rows = sorted(rows, key=lambda r: r["timestamp"])
    hits = defaultdict(list)
    by_sender = defaultdict(list); by_receiver = defaultdict(list)
    for r in rows:
        by_sender[r["sender_account"]].append(r); by_receiver[r["receiver_account"]].append(r)
    # Structuring: repeated transfers from one sender in a just-below-threshold band.
    cfg = rules["structuring"]["threshold"]
    if rules["structuring"]["enabled"]:
        for sender, txs in by_sender.items():
            for tx in txs:
                window = [x for x in txs if tx["timestamp"]-timedelta(hours=cfg["window_hours"]) <= x["timestamp"] <= tx["timestamp"] and cfg["min_amount"] <= float(x["amount"]) < cfg["max_amount"]]
                if len(window) >= cfg["min_count"]:
                    for x in window: hits[x["transaction_id"]].append("structuring")
    # Fan-in and fan-out over a calendar-day bucket, consistent with report's batch approximation.
    if rules["fan_in"]["enabled"]:
        for receiver, txs in by_receiver.items():
            for tx in txs:
                day = tx["timestamp"].date()
                group = [x for x in txs if x["timestamp"].date() == day]
                if len({x["sender_account"] for x in group}) >= rules["fan_in"]["threshold"]["min_accounts"]:
                    for x in group: hits[x["transaction_id"]].append("fan_in")
    if rules["fan_out"]["enabled"]:
        for sender, txs in by_sender.items():
            for tx in txs:
                group = [x for x in txs if x["timestamp"].date() == tx["timestamp"].date()]
                if len({x["receiver_account"] for x in group}) >= rules["fan_out"]["threshold"]["min_accounts"]:
                    for x in group: hits[x["transaction_id"]].append("fan_out")
    # Deposit-send: cash deposit followed by a near-equal outgoing transaction.
    if rules["deposit_send"]["enabled"]:
        cfg = rules["deposit_send"]["threshold"]
        for deposit in rows:
            if "cash" not in str(deposit.get("payment_type", "")).lower() or "deposit" not in str(deposit.get("payment_type", "")).lower(): continue
            for outgoing in by_sender.get(deposit["receiver_account"], []):
                gap = (outgoing["timestamp"] - deposit["timestamp"]).total_seconds() / 3600
                if 0 <= gap <= cfg["window_hours"] and float(outgoing["amount"]) >= float(deposit["amount"]) * cfg["ratio"]:
                    hits[deposit["transaction_id"]].append("deposit_send"); hits[outgoing["transaction_id"]].append("deposit_send")
    # Bounded cycle search: simple directed paths, up to configured depth.
    if rules["cycle"]["enabled"]:
        cfg = rules["cycle"]["threshold"]; edges = defaultdict(list)
        for r in rows: edges[r["sender_account"]].append(r)
        def walk(start, node, path, depth):
            if depth >= cfg["max_depth"]: return
            for edge in edges.get(node, []):
                if edge["transaction_id"] in path: continue
                if (edge["timestamp"] - path_times[path[-1]]).total_seconds()/3600 > cfg["max_gap_hours"] if path else False: continue
                if edge["receiver_account"] == start and path:
                    for tid in path + [edge["transaction_id"]]: hits[tid].append("cycle")
                elif edge["receiver_account"] not in visited:
                    visited.add(edge["receiver_account"]); path_times[edge["transaction_id"]] = edge["timestamp"]
                    walk(start, edge["receiver_account"], path + [edge["transaction_id"]], depth+1)
                    visited.remove(edge["receiver_account"])
        path_times = {r["transaction_id"]: r["timestamp"] for r in rows}
        for r in rows:
            visited = {r["sender_account"], r["receiver_account"]}
            walk(r["sender_account"], r["receiver_account"], [r["transaction_id"]], 1)
    # Behavioural change relative to historical account average (earlier records only).
    if rules["behavioural_change"]["enabled"]:
        cfg = rules["behavioural_change"]["threshold"]; history = defaultdict(list)
        for r in rows:
            vals = history[r["sender_account"]]
            if len(vals) >= 3 and float(r["amount"]) > (sum(vals)/len(vals))*cfg["baseline_multiplier"]:
                hits[r["transaction_id"]].append("behavioural_change")
            vals.append(float(r["amount"]))
    alerts = []
    weights = {k: v["weight"] for k,v in rules.items()}
    for tid, names in hits.items():
        names = sorted(set(names)); score = min(100, sum(weights[n] for n in names))
        if score >= 30:
            alerts.append({"transaction_id": tid, "matched_rules": names, "risk_score": score})
    return alerts
