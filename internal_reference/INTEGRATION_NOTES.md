# Integration Notes

## Why the v4 integration uses two workspaces

The v3 customer POC and the development-team package have different schemas and workflow assumptions. Combining them into one database on the day of the customer demonstration would add avoidable migration risk.

v4 therefore uses a gateway pattern:

- `/` mounts the customer validation and evidence application.
- `/engine/` mounts the development team's discovery and comparison engine.
- both read the same `.env` for authentication and provider configuration;
- each uses its own local database;
- navigation links connect the two applications.

This preserves all 78 automated tests while providing one customer-facing URL and startup process.

## Integrated capabilities

| Capability | Customer workspace | Discovery engine |
|---|---:|---:|
| Executive customer metrics | Yes | Run metrics |
| Google/Grab live adapters | Connector-ready | Yes |
| Geographic sweep | No | Yes |
| Reciprocal probes | Evidence display | Yes |
| Explainable matching | Yes | Yes |
| 16 Google checks | Yes | No |
| Evidence repository | Yes | Source payloads |
| Independent QA | Yes | No |
| Controlled customer export | Yes | Comparison report |
| Cost guardrails | Cost screen | Yes |

## Production consolidation path

1. Move both databases to PostgreSQL/PostGIS.
2. Establish canonical project, source-record and POI identifiers.
3. Migrate provider places, matches, probes and run costs into common lineage tables.
4. Connect provider-run outputs directly to validation queues.
5. Add object storage, SSO, secrets manager, monitoring and load testing.
6. Run reconciliation and regression testing before retiring the dual-workspace pattern.
