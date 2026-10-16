# Quality and Release Rules

## D eligibility

A usable non-Google POI requires:

- verified business identity and salon category
- usable street-level address, city, latitude, longitude, and acceptable coordinate precision
- at least one actionable contact channel
- primary source and evidence reference
- extraction date and activity evidence
- `GOOGLE_ABSENT_VERIFIED` with complete 16-step review
- confidence at or above project threshold

A critical-field failure overrides the total confidence score.

## Quality tiers

- Gold: score at or above project Gold threshold plus complete high-quality evidence
- Silver: meets every D requirement with adequate evidence
- Research: unresolved or missing a mandatory field
- Rejected: duplicate, closed, wrong category, fake/suspicious, insufficient location, or unverifiable

## Release control

Customer release requires:

1. D eligibility
2. independent QA status `PASSED`
3. non-demo record
4. no unresolved rework/rejection

Every QA review stores the reviewer, checklist, defects, notes, and independent-review flag. Strict export includes only release-approved records.
