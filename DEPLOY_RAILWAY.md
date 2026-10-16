# Deploying JSAN GeoDiscover to Railway

The application ships as one web service backed by one PostgreSQL database. On
first boot it loads a bundled snapshot of the data already fetched from the
providers (~41k provider places, the area sweeps and their resolved clusters,
the demo project) into the empty database, so the deployment comes up populated
rather than blank. The load is idempotent — a redeploy against a database that
already holds data skips it — so redeploying is always safe.

---

## 1. Create the project

1. Push this repository to GitHub.
2. In Railway choose **New Project → Deploy from GitHub repo** and pick it.
3. Railway reads `railway.json` and builds the root `Dockerfile`. No build
   settings need changing.

## 2. Add the database

In the same project choose **New → Database → Add PostgreSQL**. Railway creates
it and exposes `DATABASE_URL` to the project.

## 3. Set the variables

On the web service, **Variables → Raw Editor**, paste this and fill in the
secrets:

```
ENGINE_DATABASE_URL=${{Postgres.DATABASE_URL}}

JWT_SECRET=<64+ random characters>
DEMO_ADMIN_EMAIL=admin@jsanconsulting.com
DEMO_ADMIN_PASSWORD=<strong password>

CORS_ORIGINS=http://localhost:8000
```

Generate the secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`${{Postgres.DATABASE_URL}}` is Railway's reference syntax — it resolves to the
PostgreSQL database in the same project. `ENGINE_DATABASE_URL` takes precedence,
but if you set only `DATABASE_URL` the engine picks it up automatically.

Optional provider keys, all off by default (the app only shows data it fetched;
with no keys it still serves the bundled snapshot):

```
GOOGLE_MAPS_API_KEY=
HERE_API_KEY=
AWS_LOCATION_API_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

Optional boot controls:

```
SEED_ON_BOOT=true      # set false to come up with an empty engine
DB_WAIT_SECONDS=60     # how long boot waits for Postgres to accept connections
```

## 4. Deploy and open it

Deploy, then **Settings → Networking → Generate Domain**. The service serves the
app at `/` and reports health at `/health` (configured in `railway.json`).

---

## The administrator login

| Account | Role | Password |
|---|---|---|
| `DEMO_ADMIN_EMAIL` | Super admin | `DEMO_ADMIN_PASSWORD` |

The administrator is created — or its password reset — on every boot, so
rotating `DEMO_ADMIN_PASSWORD` and redeploying changes the sign-in. If you leave
`DEMO_ADMIN_EMAIL` unset it defaults to `admin@example.com`.

---

## What each deploy does

`release.py` runs on boot (the `startCommand` in `railway.json`) and is safe to
repeat:

1. Waits for the database to accept connections (up to `DB_WAIT_SECONDS`).
2. Creates the `engine` schema and all tables, and reconciles any added columns.
3. If the engine is empty and `SEED_ON_BOOT` is true, streams every row from the
   bundled `discovery_engine_seed.db.gz` snapshot into it, then realigns the
   Postgres id sequences.
4. Creates or refreshes the administrator login from the environment.
5. Starts uvicorn on `$PORT` with proxy headers enabled.

To refresh the shipped data, regenerate the snapshot from a local run and commit
it:

```bash
cd backend
python -c "import sqlite3,gzip,shutil,os; \
sqlite3.connect('discovery_engine.db').execute(\"VACUUM INTO 'seed.tmp'\"); \
shutil.copyfileobj(open('seed.tmp','rb'), gzip.open('discovery_engine_seed.db.gz','wb',9)); \
os.remove('seed.tmp')"
```

A redeploy will not reload it over existing data; load it into a fresh database,
or clear the engine schema first.

---

## Why the engine lives in its own schema

The engine's table names (`users`, `projects`, `provider_places`, `exports`,
`audit_logs` and others) are generic enough to collide with anything else in a
shared database, so on PostgreSQL the engine is confined to its own `engine`
schema, created automatically on boot. On SQLite these are just one file, so no
schema is involved. Nothing else needs configuring either way.

---

## Things to know

**The database is durable; the container filesystem is not.** Everything the app
shows lives in PostgreSQL and survives redeploys. Anything written to the
container filesystem (for example evidence files under `EVIDENCE_STORAGE_PATH`)
is replaced on every deploy — attach a Railway Volume if you need it kept.

**Scraping runs in-process.** A discovery job runs on a background thread inside
the web container, so a redeploy mid-run cancels it; just start it again. Records
already written keep their findings, and any sweep left `RUNNING` by a restart is
marked interrupted on the next boot rather than shown as live.

---

## Running the same image locally

```bash
docker build -t geodiscover .
docker run --rm -p 8000:8000 \
  -e JWT_SECRET=local-dev-secret-change-me \
  -e DEMO_ADMIN_PASSWORD=local-admin-pass \
  geodiscover
```

With no `ENGINE_DATABASE_URL` the engine falls back to a local SQLite file inside
the container and loads the bundled snapshot into it. Point `ENGINE_DATABASE_URL`
at a PostgreSQL instance to exercise the real deployment path. Then open
<http://localhost:8000>.

---

## If a deploy fails

| Symptom | Cause |
|---|---|
| `Database not ready yet; retrying...` then a crash | `DATABASE_URL`/`ENGINE_DATABASE_URL` unset or the database still starting. Confirm the reference resolves, or raise `DB_WAIT_SECONDS`. |
| `Can't load plugin: sqlalchemy.dialects:postgres` | A URL bypassed normalisation. Confirm it starts with `postgres://`, `postgresql://` or `postgresql+psycopg://`. |
| `relation "users" already exists` | The engine URL is not schema-isolated. Confirm you deployed the current `discovery_engine/database.py`. |
| Health check times out | First boot loads ~46k rows. `healthcheckTimeout` is 300s; raise it if the database is slow. |
| Login fails after changing the password | Redeploy — the admin password is applied at boot. |
