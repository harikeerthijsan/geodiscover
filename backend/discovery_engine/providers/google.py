"""Google Places API (New) adapter.

Sweep uses places:searchNearby, which caps at 20 results with no pagination, so
saturation is detected and handled by adaptive tile subdivision in the sweep service.
Probe uses places:searchText.

The sweep field mask is deliberately restricted to the Essentials + Pro SKU tiers.
Contact fields (phone, website) are Enterprise tier and are fetched only by details()
for records that survive into the deliverable.
"""
from __future__ import annotations

import re
import time

import httpx

from ..config import get_settings
from ..models import Provider
from ..services.geo import Tile
from .base import ProviderError, ProviderPlaceDTO, SweepResult


class QuotaExhausted(ProviderError):
    """A per-day quota was hit. Retrying today will not help."""


def _is_daily_quota(body: str) -> bool:
    lowered = body.lower()
    return "quota" in lowered and "per day" in lowered

SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

def default_included_types() -> list[str]:
    """Every Place Type the unified taxonomy knows, capped at the API's 50 limit.

    A caller that wants full category coverage should iterate the taxonomy's sweep
    plan instead, one request per category group; this flat default exists so a
    sweep with no explicit types is broad rather than silently narrow.
    """
    from ..services.taxonomy import GOOGLE_TYPE_GROUPS

    seen: list[str] = []
    for types in GOOGLE_TYPE_GROUPS.values():
        for value in types:
            if value not in seen:
                seen.append(value)
    return seen[:50]

NEARBY_MAX_RESULTS = 20  # hard API ceiling


class GooglePlacesAdapter:
    provider = Provider.GOOGLE

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        settings = get_settings()
        self.settings = settings
        self.api_key = api_key or settings.google_maps_api_key
        if not self.api_key:
            raise ProviderError("GOOGLE_MAPS_API_KEY is not configured")
        self._client = client or httpx.Client(timeout=settings.provider_request_timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # --- transport ---------------------------------------------------------

    def _post(self, url: str, body: dict, field_mask: str) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask,
        }
        last_error: Exception | None = None
        for attempt in range(self.settings.provider_max_retries):
            try:
                response = self._client.post(url, json=body, headers=headers)
                if response.status_code == 429 and _is_daily_quota(response.text):
                    # A per-day quota does not recover from backoff. Fail immediately
                    # with an actionable message instead of burning the retry budget.
                    # Keep enough of the body to include the limit value and the
                    # quota metric name: Google states both, and 200 characters cut
                    # off exactly the part that says what the ceiling actually is.
                    raise QuotaExhausted(
                        "Google daily quota exhausted for this API. Raise it in the "
                        "Google Cloud console under APIs & Services > Places API (New) > "
                        f"Quotas, or resume tomorrow. Detail: {response.text[:900]}"
                    )
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = ProviderError(f"Google returned {response.status_code}: {response.text[:300]}")
                    time.sleep(2**attempt)
                    continue
                if response.status_code >= 400:
                    raise ProviderError(f"Google returned {response.status_code}: {response.text[:300]}")
                return response.json()
            except httpx.HTTPError as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise ProviderError(f"Google request failed after retries: {last_error}")

    # --- mapping -----------------------------------------------------------

    @staticmethod
    def _address_part(place: dict, *types: str) -> str | None:
        """Pull one component out of addressComponents by its Google type."""
        for wanted in types:
            for component in place.get("addressComponents") or []:
                if wanted in (component.get("types") or []):
                    return component.get("longText") or component.get("shortText")
        return None

    def _to_dto(self, place: dict) -> ProviderPlaceDTO:
        location = place.get("location") or {}
        display = place.get("displayName") or {}
        return ProviderPlaceDTO(
            provider=Provider.GOOGLE,
            provider_place_id=place.get("id") or "",
            name=display.get("text") or place.get("name") or "",
            categories=list(place.get("types") or []),
            address=place.get("formattedAddress"),
            city=self._address_part(place, "locality", "administrative_area_level_2"),
            province=self._address_part(place, "administrative_area_level_1"),
            postal_code=self._address_part(place, "postal_code"),
            lat=location.get("latitude"),
            lng=location.get("longitude"),
            phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber"),
            website=place.get("websiteUri"),
            business_status=place.get("businessStatus"),
            raw=place,
        )

    # --- operations --------------------------------------------------------

    def sweep(self, tile: Tile, included_types: list[str] | None = None) -> SweepResult:
        """One searchNearby call.

        Callers normally pass one unified-category type group per call, which is how
        both the city job and the area sweep achieve full coverage. Omitting them
        falls back to a broad cross-category default.
        """
        body = {
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": tile.lat, "longitude": tile.lng},
                    "radius": float(tile.radius_m),
                }
            },
            # searchNearby accepts at most 50 includedTypes per request.
            "includedTypes": (included_types or default_included_types())[:50],
            "maxResultCount": NEARBY_MAX_RESULTS,
            # DISTANCE (not POPULARITY) so that a full page of results is a reliable
            # saturation signal rather than a silent truncation of the long tail.
            "rankPreference": "DISTANCE",
            "languageCode": self.settings.google_language_code,
            "regionCode": self.settings.google_region_code,
        }
        try:
            payload = self._post(SEARCH_NEARBY_URL, body, self.settings.google_sweep_field_mask)
        except ProviderError as exc:
            # Google rejects the WHOLE request if any single includedType is invalid,
            # so one bad entry in a category group silently destroys that category and
            # every category queued behind it. Drop the offending types and retry once
            # rather than losing the sweep to a typo.
            unsupported = re.findall(r"Unsupported types: ([^.\"]+)", str(exc))
            if not unsupported:
                raise
            drop = {name.strip() for chunk in unsupported for name in chunk.split(",")}
            remaining = [t for t in body["includedTypes"] if t not in drop]
            if not remaining:
                return SweepResult(places=[], api_calls=1, saturated=False)
            body["includedTypes"] = remaining
            payload = self._post(SEARCH_NEARBY_URL, body, self.settings.google_sweep_field_mask)
        places = payload.get("places") or []
        return SweepResult(
            places=[self._to_dto(p) for p in places],
            api_calls=1,
            saturated=len(places) >= NEARBY_MAX_RESULTS,
        )

    def probe(self, name: str, lat: float, lng: float, address: str | None) -> SweepResult:
        query = " ".join(part for part in [name, address] if part).strip()
        body = {
            "textQuery": query[:400],
            "locationBias": {
                "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 500.0}
            },
            "maxResultCount": 5,
            "languageCode": self.settings.google_language_code,
            "regionCode": self.settings.google_region_code,
        }
        payload = self._post(SEARCH_TEXT_URL, body, self.settings.google_sweep_field_mask)
        return SweepResult(places=[self._to_dto(p) for p in payload.get("places") or []], api_calls=1)

    def details(self, provider_place_id: str) -> ProviderPlaceDTO:
        """Enterprise-tier enrichment. Call only on records kept in the deliverable."""
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": self.settings.google_detail_field_mask,
        }
        response = self._client.get(PLACE_DETAILS_URL.format(place_id=provider_place_id), headers=headers)
        if response.status_code >= 400:
            raise ProviderError(f"Google details returned {response.status_code}: {response.text[:300]}")
        return self._to_dto(response.json())
