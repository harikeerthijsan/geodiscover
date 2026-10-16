# Deployment

## Recommended customer demonstration: Windows

Use `START_GEODISCOVER_WINDOWS.bat`. It creates the Python environment, installs dependencies, migrates the customer database, loads both controlled datasets and starts the integrated gateway.

URLs:

- Customer workspace: `http://localhost:8000/`
- Live discovery engine: `http://localhost:8000/engine/`
- Cost & Scale: `http://localhost:8000/#costs`

## Manual local start

From `backend`:

```powershell
Copy-Item .env.example .env
notepad .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe bootstrap.py
.\.venv\Scripts\python.exe -m uvicorn gateway:app --host 127.0.0.1 --port 8000
```

## Docker demonstration

At the package root:

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up --build
```

The Docker demonstration uses persistent SQLite volumes for the two independently tested workspaces and Redis for future background jobs.

## Why PostGIS is not forced in today's integrated package

The v3 customer application and the team engine have different table definitions and overlapping table names. A same-day merge into one PostgreSQL schema would create unnecessary migration risk. The production path is to use separate PostgreSQL schemas/databases first, then consolidate canonical POI and lineage models after reconciliation and regression testing.

## Production checklist

Use managed PostgreSQL/PostGIS, managed Redis, a secrets manager, S3-compatible evidence storage, TLS, SSO/MFA, automated backups, monitoring, dependency scanning, load tests and security review. Rotate any credentials previously committed to source control. Do not expose the demo administrator publicly.
