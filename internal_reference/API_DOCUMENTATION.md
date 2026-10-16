# API Documentation

Interactive OpenAPI is available at `/docs` when the service is running.

Main API groups under `/api/v1`:

- `/auth` — login and current user
- `/projects` — project creation and configuration
- `/sources` — connector management and connector runs
- `/imports` — CSV/XLSX source ingestion
- `/candidates` — workbench, updates, Google review and history
- `/entity-resolution` — source comparison, match decisions, merge/unmerge
- `/evidence` — evidence items, file upload/download, timeline and ZIP
- `/qa` — submission, independent review and scorecard
- `/operations` — call-validation and local-research tasks
- `/dashboard` — A–I, ratios, comparison and quality KPIs
- `/maps` — coordinate-based GeoJSON
- `/exports` — validation and XLSX deliverables
- `/audit` — immutable action history

All mutation routes require JWT authentication and role checks. List endpoints use project filters; candidate lists provide pagination and status filters. Import operations preserve raw source rows and hashes. Strict export is rejected when no non-demo, QA-approved release records exist.
