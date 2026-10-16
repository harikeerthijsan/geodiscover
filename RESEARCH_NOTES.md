# Research notes — official sources checked 30 July 2026

## Google Places

Google Places Text Search and Nearby Search require explicit field masks. Narrow field masks reduce response size, latency and the risk of triggering higher-priced data tiers.

- https://developers.google.com/maps/documentation/places/web-service/choose-fields
- https://developers.google.com/maps/documentation/places/web-service/text-search
- https://developers.google.com/maps/documentation/places/web-service/nearby-search

Google publishes separate global and India pricing tables. Pricing is per billable event, aggregated monthly, with usage caps and volume tiers.

- https://developers.google.com/maps/billing-and-pricing/pricing
- https://developers.google.com/maps/billing-and-pricing/pricing-india

## GrabMaps and Amazon Location

GrabMaps provides Southeast Asia-focused place and map data through Amazon Location in supported markets. Account-specific pricing and data-use terms must be confirmed in the JSAN AWS account before quoting a stored-results programme.

- https://docs.aws.amazon.com/location/latest/developerguide/GrabMaps.html
- https://aws.amazon.com/location/pricing/

## Map UI

MapLibre GL JS supports browser-based interactive maps, GeoJSON sources, filtering and point clustering.

- https://maplibre.org/maplibre-gl-js/docs/
