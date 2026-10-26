$ErrorActionPreference = 'Stop'
Write-Host "AML Watchtower - local setup" -ForegroundColor Cyan
Write-Host "This writes a local .env file. It will not be included in the project ZIP."
if (Test-Path .env) {
  $overwrite = Read-Host ".env already exists. Replace it? (y/N)"
  if ($overwrite -ne 'y' -and $overwrite -ne 'Y') { Write-Host "Keeping existing .env"; exit 0 }
}
$dbUrl = Read-Host "Paste your Supabase PostgreSQL Session Pooler URI (port 5432)"
if (-not $dbUrl.StartsWith('postgresql://') -and -not $dbUrl.StartsWith('postgres://')) { throw "The database URI must start with postgresql:// or postgres://" }
$secretBytes = New-Object byte[] 48
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($secretBytes)
$jwtSecret = [Convert]::ToBase64String($secretBytes).Replace('+','-').Replace('/','_').TrimEnd('=')
$rng.Dispose()
$lines = @(
  "DATABASE_URL=$dbUrl",
  "JWT_SECRET=$jwtSecret",
  "DEMO_ANALYST_EMAIL=analyst@example.com",
  "DEMO_ANALYST_PASSWORD=ChangeMe123!",
  "DEMO_ADMIN_EMAIL=admin@example.com",
  "DEMO_ADMIN_PASSWORD=ChangeMe123!",
  "KAFKA_BOOTSTRAP_SERVERS=kafka:29092",
  "REDIS_URL=redis://redis:6379/0",
  "CORS_ORIGINS=http://localhost:3000"
)
Set-Content -Path .env -Value $lines -Encoding ascii
Write-Host "Created .env with a generated JWT secret and demo credentials." -ForegroundColor Green
Write-Host "Demo login: analyst@example.com / ChangeMe123! or admin@example.com / ChangeMe123!. Change these before sharing. Keep .env private."
Write-Host "Next run: .\run-demo.ps1"
