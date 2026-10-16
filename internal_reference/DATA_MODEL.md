# Data Model

Core entities:

- `users`, `projects`, `source_connectors`, `connector_runs`
- `raw_source_records` with raw JSON and SHA-256
- `poi_candidates`, `poi_entities`, `entity_match_scores`
- `duplicate_groups`, `duplicate_memberships`
- `google_checks` with per-check queries/results/evidence
- `evidence_items` with file metadata and hash
- `call_jobs`, `research_tasks`, `qa_reviews`
- `status_history`, `exports`, `audit_logs`

The model separates immutable source evidence from normalized candidates and canonical entities. Manual decisions do not erase the original source record. Candidate release state is derived from eligibility, QA, and demo status.
