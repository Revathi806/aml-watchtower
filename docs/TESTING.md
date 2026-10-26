# Test and evidence log

Record only actual results from your own execution.

| Test | Command / action | Expected evidence | Actual result |
|---|---|---|---|
| API health | `GET /health` | JSON status `ok` | Pending |
| Schema creation | `python scripts/init_db.py` | Successful completion | Pending |
| Import validation | `SELECT count(*) FROM core.transaction;` | Count matches import log | Pending |
| Edge integrity | Count transactions without edge rows | Zero | Pending |
| Detection | `python scripts/run_detection.py` | Alert count and execution time | Pending |
| Query plan | `EXPLAIN (ANALYZE, BUFFERS) ...` | Before/after query plans | Pending |
| Alert workflow | Resolve a test alert in UI | Status and audit row updated | Pending |
| Kafka replay | `python -m app.streaming producer` | Producer count / topic messages | Pending |
| Analytics | refresh materialized views | Dashboard updates | Pending |

Do not insert invented throughput, accuracy, precision, recall, or latency values into the report.
