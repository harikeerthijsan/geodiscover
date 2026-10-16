# Source Connector Guide

Connector modes:

- `LIVE`: invokes an authorized provider adapter and fails visibly when credentials are unavailable.
- `MOCK`: returns clearly labelled demonstration data only.
- `FILE_UPLOAD`: imports customer/partner-authorized CSV or XLSX data.
- `MANUAL`: supports analyst and researcher entry.

Each run stores query, geography, status, raw response, discovered/imported counts, errors, and timestamps. Every imported result creates an immutable raw-source record before normalization.

Included adapters:

- Google Places Text Search
- GrabMaps through an Amazon Location place index
- Apify actors for Instagram, TikTok, and Facebook
- file upload and manual workflows

Directory, booking, official-site, and other-map sources should use authorized files initially or implement the same adapter contract after source approval.
