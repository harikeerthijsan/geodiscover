# Google Exclusion Rules

`GOOGLE_ABSENT_VERIFIED` requires all mandatory checks:

1. Exact business name
2. Business name plus city
3. Business name plus locality
4. Business name plus complete address
5. Alternate spelling
6. Normalized name
7. Phone number
8. WhatsApp number
9. Website domain
10. Coordinate search
11. Nearby salon search
12. Branch check
13. Renamed-business check
14. Moved-location check
15. Closed-business check
16. Duplicate or merged-listing check

Each item retains check type, query, completion, result, candidate Place IDs, radius where relevant, evidence reference, notes, timestamp, and reviewer. Missing checks, incomplete items, or remaining candidate Place IDs block verified absence.

A candidate not found in an initial search remains pending or inconclusive. C is never calculated as A minus B.
