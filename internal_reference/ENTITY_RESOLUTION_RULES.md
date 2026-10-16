# Entity Resolution Rules

Default weighted score:

- normalized/alternate/branch name: 30
- coordinate proximity: 25
- phone or WhatsApp: 20
- address: 15
- website domain or social relationship: 10

Defaults:

- 80–100: probable same POI/common
- 60–79: possible match/manual review
- below 60: separate or unresolved/source-only

The match record stores every component, total score, distance in metres, weights, match indicators, source record IDs, and branch names. A human can decide same POI, separate, or unresolved with a mandatory reason. Same-POI decisions create a canonical entity and duplicate group without deleting source candidates. Unmerge removes the candidate from the entity while retaining the audit history.
