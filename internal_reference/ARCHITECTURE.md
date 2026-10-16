# Architecture v4.0

## Integrated gateway

```text
Browser
  |
  v
FastAPI gateway :8000
  |-- /              Customer validation workspace
  |     |-- customer_demo.db
  |     |-- evidence_storage_customer/
  |     `-- dashboard, comparison, exclusion, evidence, QA, map, exports, costs
  |
  `-- /engine/       Discovery and comparison engine
        |-- discovery_engine.db
        `-- Google Places / GrabMaps adapters, sweep, matching, probes, jobs, costs
```

## Customer workspace

- FastAPI and SQLAlchemy
- controlled Denpasar source importer
- explicit Google status model
- 16-check Google-exclusion records
- evidence and hash metadata
- entity resolution and reversible merge lineage
- local research and call-validation queues
- independent QA and controlled export
- MapLibre/GeoJSON map
- cost and scale endpoint

## Discovery engine

- Google Places API (New) adapter
- Amazon Location/GrabMaps adapter
- Indonesia city and boundary catalogue
- tile-based sweep and category filtering
- explainable name, address, distance and relationship matching
- reciprocal uniqueness probing
- area-coverage evidence
- call/spend budget guardrails
- comparison workbook and GeoJSON outputs

## Current integration decision

The applications retain separate databases because their schemas overlap but are not identical. This preserves today's tested behavior and avoids a high-risk same-day migration.

## Production target

- managed PostgreSQL/PostGIS with separate schemas during transition
- canonical POI, provider-place, match, probe and evidence identifiers
- Redis/Celery for jobs
- S3-compatible evidence storage
- SSO/MFA and project isolation
- secrets manager
- structured logs, metrics, alerts and audit retention
- reconciliation, load, security and failover testing
