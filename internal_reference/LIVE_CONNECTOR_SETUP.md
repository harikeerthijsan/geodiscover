# Live Connector Setup

The customer meeting can use the seeded controlled-run evidence. Do not enable paid connectors during the meeting unless credentials, budget and customer approval are confirmed.

## Google Places API (New)

Set in `backend/.env`:

```text
GOOGLE_MAPS_API_KEY=<authorised server-side key>
GOOGLE_MAX_CALLS_PER_RUN=2000
GOOGLE_MAX_SPEND_PER_RUN_USD=5.0
RATE_GOOGLE_NEARBY_PER_1K=32.0
RATE_GOOGLE_TEXT_PER_1K=32.0
RATE_GOOGLE_DETAILS_PER_1K=20.0
```

The sweep field mask is intentionally limited to Pro-tier identity/location fields. Phone and website enrichment is separated because those fields can move requests to a higher SKU tier.

Official references:

- https://developers.google.com/maps/billing-and-pricing/pricing
- https://developers.google.com/maps/billing-and-pricing/pricing-india
- https://developers.google.com/maps/documentation/places/web-service/nearby-search

Follow Google attribution, storage and licence requirements. Place IDs can be retained, but other content is subject to current terms and permitted caching/storage rules.

## GrabMaps through Amazon Location Service

Set one approved authentication method:

```text
AWS_REGION=ap-southeast-1
AWS_LOCATION_API_KEY=<Amazon Location API key>
```

or approved IAM credentials:

```text
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=
```

Because GeoDiscover persists provider results, retain:

```text
GRAB_INTENDED_USE=Storage
```

Set the account's verified Stored rate before relying on cost totals:

```text
RATE_GRAB_SEARCH_TEXT_PER_1K=<verified AWS rate>
```

Official references:

- https://aws.amazon.com/location/pricing/
- https://aws.amazon.com/about-aws/whats-new/2024/06/amazon-location-service-grabmaps/

## Social and directory discovery

The customer workspace retains adapter interfaces for approved social, booking and directory sources. Costs vary by source, actor and usage. Configure only approved sources and retain extraction method, URL, timestamp and evidence.

## Security

- Never commit `.env`.
- Use least-privilege server-side credentials.
- Restrict API keys by API, IP/domain and environment.
- Use a secrets manager in production.
- Rotate any credential previously committed to Git or shared in an archive.
- Keep per-run spend and call caps enabled.
