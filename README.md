# AML Watchtower — Transaction Monitoring Platform

A cloud-connected academic prototype based on the accompanying project report. It demonstrates normalized PostgreSQL storage, explainable rule-based AML alerts, an analyst dashboard, Kafka replay infrastructure, Redis, Airflow, FastAPI, React and Docker Compose.

> **Important:** This is a coursework prototype using synthetic/historical data. A rule match is not proof of criminal activity. Do not connect it to real customer accounts or use it for operational compliance decisions. The project is not production-hardened.

## Fastest setup on Windows

1. Install and start **Docker Desktop**. Ensure Docker Compose works in PowerShell (`docker compose version`).
2. Extract this ZIP and open the extracted `aml-platform` folder in PowerShell.
3. Run `Set-ExecutionPolicy -Scope Process Bypass` if PowerShell blocks local scripts.
4. Run `.\setup-windows.ps1`, then paste your Supabase **Session Pooler** URI (port 5432) when prompted. The URI is stored only in your local `.env` file and is not embedded in the ZIP.
5. Run `.\run-demo.ps1`. It builds the containers, creates the database schema, inserts synthetic demo transactions, runs detection and refreshes analytics.
6. Open http://localhost:3000. API documentation: http://localhost:8000/docs.

Login defaults for the coursework demo are `analyst@example.com` / `ChangeMe123!` and `admin@example.com` / `ChangeMe123!`. The `.env` file is excluded from version control; change demo passwords before sharing or hosting the project.

If a command fails, inspect `docker compose ps` and `docker compose logs api`. Supabase credentials must be valid and the database password must be URL-encoded if it contains URI-reserved characters. Do not send database passwords in screenshots or commit `.env`.

## Features

- PostgreSQL schemas: `staging`, `core`, and `analytics`.
- Six configurable rule typologies: structuring, fan-in, fan-out, deposit-send, bounded cycle detection and behavioural change.
- Weighted scores capped at 100; alert threshold is 30.
- FastAPI endpoints for authentication, alerts, case notes/audit, search, analytics, and administrator-only rule configuration.
- React dashboard with KPI cards, charts, alert queue, case review, search, and rule configuration.
- Kafka transaction replay producer and Redis service included in Compose.
- Four manually triggered Airflow DAGs included in the optional `orchestration` profile.
- Supabase PostgreSQL remains a remote managed database; it is not containerized.

## Requirements

- Docker Desktop with Compose v2
- A Supabase project and its PostgreSQL Session Pooler connection string
- Python 3.11+ only if running scripts outside Docker
- A SAML-D CSV file obtained from the dataset's official/research source

## 1. Configure Supabase

1. Create a Supabase project.
2. Open **Project Settings → Database → Connection string** and select the **Session pooler** option (port 5432).
3. Copy `.env.example` to `.env` in the project root.
4. Set `DATABASE_URL` to the exact Session Pooler URI, including `sslmode=require`.
5. Replace `JWT_SECRET` with a long random secret. Change the demo passwords before sharing the project.
6. Keep `.env` private; it is excluded by `.gitignore`.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

## 2. Create the schema

From the project root, create a Python environment if you do not want to use Docker:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "."
python scripts/init_db.py
```

Run `init_db.py` from the `backend` folder. It creates schemas, tables, indexes, audit trigger, materialized views, and default rule configuration, then inserts the two demo analyst identities.

## 3. Load transactions

Download the SAML-D CSV from the source used in your report. Do not assume every downloaded version uses identical column names; the loader supports common SAML-D names and reports unparseable rows by skipping them. Review the CSV headers first.

```powershell
cd backend
$env:PYTHONPATH = "."
python scripts/load_csv.py "C:\path\to\SAML-D.csv" --limit 200000
```

The loader uses a simplified sequential transaction ID based on CSV row position. For repeatable production-grade ingestion, preserve a stable source transaction key and make the import restartable. This loader is intended for a course demonstration and should be reviewed before importing multiple overlapping files.

### Optional: populate a small synthetic smoke-test dataset

If you want to test the dashboard before obtaining the SAML-D dataset, run this after schema initialization:

```powershell
cd backend
$env:PYTHONPATH = "."
python scripts/seed_demo.py
```

This inserts deterministic synthetic transactions and is intended only for UI smoke testing. Use a clean test database or keep demo IDs separate from your eventual CSV import.

## 4. Run batch detection

```powershell
cd backend
$env:PYTHONPATH = "."
python scripts/run_detection.py
```

Detection uses transaction fields, account relationships, payment types, timestamps and rule configuration. `source_label`/ground-truth labels are not passed to the detector; labels are retained only for later evaluation. The bounded graph rule is computationally expensive on large or highly connected datasets, so start with a small sample.

## 5. Start the app with Docker Compose

Return to the project root. Ensure `.env` is configured, then run:

```powershell
docker compose up --build -d
docker compose ps
```

Open:

- Frontend: http://localhost:3000
- API documentation: http://localhost:8000/docs
- API health: http://localhost:8000/health
- Kafka host listener: `localhost:9092`
- Redis: `localhost:6379`

Demo logins (change before sharing):

- Analyst: `analyst@example.com` / `ChangeMe123!`
- Admin: `admin@example.com` / `ChangeMe123!`

If you change the credentials in `.env`, restart the API: `docker compose up -d --build api`.

## 6. Replay events into Kafka

With Compose running, open a second terminal:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "."
# The host-run producer uses localhost:9092; ensure DATABASE_URL is also set in this terminal.
python -m app.streaming producer
```

The producer publishes up to 20,000 historical events to the `transactions` topic. The consumer uses Redis sorted sets for 24-hour event-time windows and applies structuring, fan-in, and fan-out rules, writing deduplicated alerts to PostgreSQL. Run the producer first, then the consumer. This is historical replay, not a live financial-institution feed. A WebSocket push feed is not implemented.

## 7. Start Airflow (optional)

```powershell
docker compose --profile orchestration up -d airflow
```

Visit http://localhost:8080. Airflow standalone creates its initial login credentials in the Airflow container logs; inspect them with `docker compose logs airflow`. The four DAGs are manually triggered. The container uses SQLite metadata for a low-resource coursework demo, not a production setup.

## Main API endpoints

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `POST` | `/auth/login` | Public | Issue JWT for configured demo account |
| `GET` | `/me` | Authenticated | Current identity |
| `GET` | `/alerts` | Authenticated | Filter and page alert queue |
| `GET` | `/alerts/{id}` | Authenticated | Case, transaction, notes and audit |
| `PATCH` | `/alerts/{id}` | Authenticated | Change status and add note |
| `GET` | `/analytics/kpis` | Authenticated | KPI, time series and typology summaries |
| `GET` | `/search?q=...` | Authenticated | Search alerts by account/transaction/type |
| `GET` | `/rules` | Authenticated | List detection rules |
| `PUT` | `/rules/{name}` | Admin | Update enabled state, weight and threshold |
| `GET` | `/analysts/workload` | Admin | Active assigned workload |
| `POST` | `/admin/refresh-analytics` | Admin | Refresh dashboard materialized views |

## Troubleshooting

- **Database connection fails:** verify the Supabase Session Pooler host, port 5432, password URL-encoding, and `sslmode=require`.
- **Dashboard loads but shows database errors:** initialize the schema and load at least some transactions; a healthy API does not mean tables already contain data.
- **No alerts:** run `python scripts/run_detection.py`; the system does not fabricate alert records.
- **Frontend returns 502:** check `docker compose ps` and `docker compose logs api`; confirm `.env` has valid configuration.
- **Kafka not healthy:** inspect `docker compose logs kafka`; wait until the broker health check passes before publishing.
- **Rule run is slow:** use a smaller dataset, especially for bounded cycle detection.
- **Ports in use:** change host-side mappings in `docker-compose.yml` while retaining internal container ports.

## Verification checklist

- [ ] `/health` returns `status: ok`.
- [ ] `init_db.py` completes without SQL errors.
- [ ] Row counts in `core.transaction` match the intended import count.
- [ ] Sender and receiver edges exist for loaded transactions.
- [ ] `run_detection.py` produces candidate alerts when rule patterns exist.
- [ ] Analyst login works and an analyst cannot edit rule configuration.
- [ ] Alert status updates create audit entries.
- [ ] Dashboard charts reflect the materialized view refresh.
- [ ] Kafka topic receives replay messages.
- [ ] Capture actual timings and results; do not invent performance metrics in the report.

## Project structure

```text
aml-platform/
├── .env.example
├── docker-compose.yml
├── backend/
│   ├── app/                 # FastAPI, auth, database and detection rules
│   ├── sql/schema.sql       # Relational schema and analytics views
│   ├── scripts/             # Initialize, load CSV, run detection
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                # React dashboard + Nginx
├── airflow/dags/            # Four manually triggered DAGs
└── docs/                    # Place run evidence and benchmark outputs here
```

## Known implementation boundaries

The package implements the core schema, six batch detection rules, a REST dashboard, a Kafka replay producer/consumer for three streaming rules, Redis sliding-window state, and Airflow task definitions. Remaining limitations include no WebSocket push feed, demo credentials rather than a persisted user-management system, no fully verified Parquet/DuckDB export pipeline, possible ID collisions if synthetic demo data and a CSV are loaded into the same database, and no independent AML model validation. Do not expose the development deployment publicly.


## Administrator features

Sign in using `DEMO_ADMIN_EMAIL` / `DEMO_ADMIN_PASSWORD` from `.env` (defaults: `admin@example.com` / `ChangeMe123!`). Admins see **User Management** and can create analyst/admin accounts, deactivate accounts, and assign alerts to active analysts from Case Review. Deactivation is a soft delete to preserve alert/audit history. An administrator cannot deactivate their own account or the last active administrator.

New users are stored in `core.analyst` with a hashed password. The schema adds `password_hash` to an existing table. Apply the updated `backend/sql/schema.sql` to your configured PostgreSQL database, then rebuild/restart with `docker compose up -d --build`. Existing environment-configured demo logins remain supported for initial setup. Keep admin credentials and `JWT_SECRET` private.
