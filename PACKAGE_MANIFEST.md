# Package manifest

## Customer-facing files

- `START_HERE.txt` — layman startup and demo order
- `README.md` — package purpose and startup commands
- `CUSTOMER_DEMO_SCRIPT.md` — 8–10 minute customer narrative
- `CURRENT_SCOPE_AND_NEXT_STEP.md` — now, next and future separation
- `RESEARCH_NOTES.md` — official Google, AWS/GrabMaps and MapLibre references
- `BUILD_VALIDATION.md` — test and claim-control results
- `sample_output/GeoDiscover_Executive_Customer_Sample_v5.xlsx` — customer workbook
- `sample_output/Executive_Summary_Preview_v5.png` — workbook preview

## Application

- `START_GEODISCOVER_WINDOWS.bat` — one-click Windows startup
- `backend/app/static/` — simplified executive UI
- `backend/app/routers/executive.py` — customer-focused APIs
- `backend/discovery_engine/` — internal future-scale discovery engine
- `sample_data/` — source workbook and templates

## Internal reference

Detailed v4 architecture, API, quality, security and connector documents were moved to `internal_reference/` so they do not complicate the customer story.
