# File Manifest

## Primary customer files

- `START_HERE.txt` — non-technical startup instructions
- `START_GEODISCOVER_WINDOWS.bat` — one-click Windows startup
- `CUSTOMER_DEMO_SCRIPT.md` — 12–15 minute speaker flow
- `CUSTOMER_CAPABILITY_MATRIX.md` — what can and cannot be claimed
- `CUSTOMER_COST_AND_SCALE.md` — cost assumptions and official source links
- `sample_output/GeoDiscover_Customer_Sample_and_Cost_v4.xlsx` — customer summary, Strong 25 and editable cost model
- `sample_output/Customer_Sample_Cost_Preview.png` — workbook preview

## Application structure

- `backend/app/` — customer validation/evidence workspace
- `backend/discovery_engine/` — development-team live discovery engine
- `backend/gateway.py` — integrated FastAPI gateway
- `backend/bootstrap.py` — prepares both local databases
- `backend/discovery_engine_seed.db` — controlled Denpasar engine seed
- `sample_data/GeoDiscover_Denpasar_Team_Live_Output.xlsx` — source comparison workbook

## Complete file list

```text
.env.example
.gitignore
API_DOCUMENTATION.md
ARCHITECTURE.md
BUILD_VALIDATION.md
CHANGELOG.md
CUSTOMER_CAPABILITY_MATRIX.md
CUSTOMER_COST_AND_SCALE.md
CUSTOMER_DEMO_SCRIPT.md
DATA_MODEL.md
DEMO_GUIDE.md
DEPLOYMENT.md
ENTITY_RESOLUTION_RULES.md
FILE_MANIFEST.md
GOOGLE_EXCLUSION_RULES.md
INTEGRATION_NOTES.md
LIVE_CONNECTOR_SETUP.md
PRODUCT_REQUIREMENTS.md
QUALITY_RULES.md
README.md
RESET_DEMO_WINDOWS.bat
SECURITY.md
SOURCE_CONNECTOR_GUIDE.md
START_GEODISCOVER_WINDOWS.bat
START_HERE.txt
backend/.env.example
backend/Dockerfile
backend/alembic.ini
backend/alembic/env.py
backend/alembic/script.py.mako
backend/alembic/versions/41a346f77a37_customer_capability_schema.py
backend/app/__init__.py
backend/app/auth.py
backend/app/config.py
backend/app/data/denpasar_customer_demo.json
backend/app/database.py
backend/app/main.py
backend/app/models.py
backend/app/routers/__init__.py
backend/app/routers/audit.py
backend/app/routers/auth.py
backend/app/routers/candidates.py
backend/app/routers/connectors.py
backend/app/routers/costs.py
backend/app/routers/customer_demo.py
backend/app/routers/dashboard.py
backend/app/routers/entity_resolution.py
backend/app/routers/evidence.py
backend/app/routers/exports.py
backend/app/routers/imports.py
backend/app/routers/maps.py
backend/app/routers/operations.py
backend/app/routers/projects.py
backend/app/routers/qa.py
backend/app/schemas.py
backend/app/seed.py
backend/app/seed_customer_demo.py
backend/app/services/audit.py
backend/app/services/connectors.py
backend/app/services/eligibility.py
backend/app/services/entity_resolution.py
backend/app/services/google_rules.py
backend/app/services/kpi.py
backend/app/services/normalization.py
backend/app/static/app.js
backend/app/static/index.html
backend/app/static/sample-template.csv
backend/app/static/styles.css
backend/app/worker.py
backend/bootstrap.py
backend/discovery_engine/__init__.py
backend/discovery_engine/auth.py
backend/discovery_engine/config.py
backend/discovery_engine/data/__init__.py
backend/discovery_engine/data/indonesia.py
backend/discovery_engine/database.py
backend/discovery_engine/main.py
backend/discovery_engine/models.py
backend/discovery_engine/providers/__init__.py
backend/discovery_engine/providers/base.py
backend/discovery_engine/providers/google.py
backend/discovery_engine/providers/grab.py
backend/discovery_engine/routers/__init__.py
backend/discovery_engine/routers/audit.py
backend/discovery_engine/routers/auth.py
backend/discovery_engine/routers/candidates.py
backend/discovery_engine/routers/comparison.py
backend/discovery_engine/routers/dashboard.py
backend/discovery_engine/routers/discovery.py
backend/discovery_engine/routers/exports.py
backend/discovery_engine/routers/imports.py
backend/discovery_engine/routers/jobs.py
backend/discovery_engine/routers/projects.py
backend/discovery_engine/schema_sync.py
backend/discovery_engine/schemas.py
backend/discovery_engine/seed.py
backend/discovery_engine/services/audit.py
backend/discovery_engine/services/comparison.py
backend/discovery_engine/services/comparison_report.py
backend/discovery_engine/services/coverage.py
backend/discovery_engine/services/eligibility.py
backend/discovery_engine/services/geo.py
backend/discovery_engine/services/jobs.py
backend/discovery_engine/services/kpi.py
backend/discovery_engine/services/matching.py
backend/discovery_engine/services/normalization.py
backend/discovery_engine/services/pricing.py
backend/discovery_engine/services/probe.py
backend/discovery_engine/services/sweep.py
backend/discovery_engine/static/app.js
backend/discovery_engine/static/index.html
backend/discovery_engine/static/sample-template.csv
backend/discovery_engine/static/styles.css
backend/discovery_engine_seed.db
backend/engine_tests/__init__.py
backend/engine_tests/conftest.py
backend/engine_tests/test_api.py
backend/engine_tests/test_comparison.py
backend/engine_tests/test_rules.py
backend/gateway.py
backend/requirements.txt
backend/tests/conftest.py
backend/tests/test_api.py
backend/tests/test_rules.py
docker-compose.yml
sample_data/GeoDiscover_Denpasar_CORE_Source_20260730.xlsx
sample_data/GeoDiscover_Denpasar_Team_Live_Output.xlsx
sample_data/customer_release_template.csv
sample_data/indonesia_salon_import_template.csv
sample_output/Customer_Sample_Cost_Preview.png
sample_output/GeoDiscover_Customer_Sample_and_Cost_v4.xlsx
team_source_exports/GeoDiscover_Denpasar_CORE_20260730_072410.xlsx
team_source_exports/GeoDiscover_Denpasar_CORE_20260730_075324.xlsx
```
