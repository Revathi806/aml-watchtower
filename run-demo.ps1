$ErrorActionPreference = 'Stop'
if (-not (Test-Path .env)) { throw "Missing .env. First run: .\setup-windows.ps1" }
Write-Host "Building and starting AML Watchtower services..." -ForegroundColor Cyan
docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed. Check Docker Desktop and run docker compose logs." }
Write-Host "Waiting briefly for services to initialize..."
Start-Sleep -Seconds 8
Write-Host "Creating database schema..."
docker compose exec -T api python scripts/init_db.py
if ($LASTEXITCODE -ne 0) { throw "Database initialization failed. Verify DATABASE_URL and Supabase network access." }
Write-Host "Inserting synthetic demo transactions..."
docker compose exec -T api python scripts/seed_demo.py
if ($LASTEXITCODE -ne 0) { throw "Demo seeding failed. Check API logs and database permissions." }
Write-Host "Running AML detection..."
docker compose exec -T api python scripts/run_detection.py
if ($LASTEXITCODE -ne 0) { throw "Detection run failed. Check API logs." }
Write-Host "Refreshing analytics..."
docker compose exec -T api python scripts/refresh_analytics.py
if ($LASTEXITCODE -ne 0) { throw "Analytics refresh failed." }
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Frontend: http://localhost:3000"
Write-Host "API docs: http://localhost:8000/docs"
Write-Host "Airflow is optional: docker compose --profile orchestration up -d airflow"
Write-Host "Open .env to get the generated analyst/admin login credentials."
