"""Coursework Airflow DAGs. Set DATABASE_URL in the Airflow environment."""
from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

with DAG('batch_graph_detection', start_date=datetime(2026,1,1), schedule=None, catchup=False, tags=['aml','batch']) as graph_dag:
    detect = BashOperator(task_id='run_rule_detection', bash_command='cd /opt/airflow/backend && python scripts/run_detection.py')

with DAG('evaluate_rules', start_date=datetime(2026,1,1), schedule=None, catchup=False, tags=['aml','evaluation']) as eval_dag:
    evaluate = BashOperator(task_id='summarize_rule_hits', bash_command='''cd /opt/airflow/backend && python - <<'PY'
import asyncio, asyncpg, os
async def main():
 c=await asyncpg.connect(os.environ['DATABASE_URL'],ssl='require')
 try:
  rows=await c.fetch("SELECT dr.rule_name,count(*)::int AS hits,count(*) FILTER (WHERE t.source_label)::int AS labelled_hits FROM core.detected_rule dr JOIN core.transaction t USING(transaction_id) GROUP BY dr.rule_name ORDER BY hits DESC")
  print('rule_name,hits,labelled_hits')
  for r in rows: print(f"{r['rule_name']},{r['hits']},{r['labelled_hits']}")
 finally: await c.close()
asyncio.run(main())
PY''')

with DAG('build_star_schema', start_date=datetime(2026,1,1), schedule=None, catchup=False, tags=['aml','analytics']) as star_dag:
    export = BashOperator(task_id='export_analytics_summary', bash_command='''cd /opt/airflow/backend && python - <<'PY'
import asyncio, asyncpg, os
async def main():
 c=await asyncpg.connect(os.environ['DATABASE_URL'],ssl='require')
 try:
  rows=await c.fetch('SELECT day,transaction_count,flagged_count,open_alert_count FROM analytics.kpi_daily ORDER BY day')
  print(f'Analytics daily rows available for local export: {len(rows)}')
  for r in rows[-5:]: print(dict(r))
 finally: await c.close()
asyncio.run(main())
PY''')

with DAG('refresh_views', start_date=datetime(2026,1,1), schedule=None, catchup=False, tags=['aml','analytics']) as refresh_dag:
    refresh = BashOperator(task_id='refresh_materialized_views', bash_command='''cd /opt/airflow/backend && python - <<'PY'
import asyncio, asyncpg, os
async def main():
 c=await asyncpg.connect(os.environ['DATABASE_URL'],ssl='require')
 try:
  for v in ['analytics.kpi_daily','analytics.typology_daily','analytics.geo_flagged']:
   await c.execute(f'REFRESH MATERIALIZED VIEW {v}')
  print('All dashboard materialized views refreshed.')
 finally: await c.close()
asyncio.run(main())
PY''')
