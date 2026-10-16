"""HERE Geocoding & Search v7 adapter, using the /browse endpoint.

/browse is the right call for area discovery: it takes a centre point, a circular
boundary and a category filter, which is exactly the shape of a tile sweep. The
alternative, /discover, is query-driven and would put HERE on the same weak
keyword footing as Grab for no reason.

Two ceilings drive the design:

  * `limit` maxes out at 100 results per call. A full page is treated as saturation
    and the sweep service subdivides the tile, the same contract Google's 20-result
    ceiling uses.
  * The category filter takes HERE's own category IDs, so the sweep iterates HERE's
    top-level roots rather than the unified categories. One unified category can
    span several HERE roots, and requesting a root twice would be billed twice.

The adapter refuses to construct without a key. There is no synthetic fallback:
a comparison is a claim about real coverage, and a fabricated record on any leg
would silently corrupt every bucket count downstream.
"""
from __future__ import annotations

import time

import httpx

from ..config import get_settings
from ..models import Provider
from ..services.geo import Tile
from .base import ProviderError, ProviderPlaceDTO, SweepResult

BROWSE_URL = "https://browse.search.hereapi.com/v1/browse"
DISCOVER_URL = "https://discover.search.hereapi.com/v1/discover"
LOOKUP_URL = "https://lookup.search.hereapi.com/v1/lookup"

BROWSE_MAX_LIMIT = 100  # hard API ceiling


class HereAdapter:
    provider = Provider.HERE

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        settings = get_settings()
        self.settings = settings
        self.api_key = api_key if api_key is not None else settings.here_api_key
        if not self.api_key:
            raise ProviderError(
                "HERE is not configured: set HERE_API_KEY in backend/.env. "
                "Create a key at platform.here.com under Access Manager > Apps > "
                "Credentials > API Keys."
            )
        self._client = client or httpx.Client(timeout=settings.provider_request_timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # --- transport ---------------------------------------------------------

    def _get(self, url: str, params: dict) -> dict:
        params = {**params, "apiKey": self.api_key}
        last_error: Exception | None = None
        for attempt in range(self.settings.provider_max_retries):
            try:
                response = self._client.get(url, params=params)
                if response.status_code == 429:
                    # HERE freemium enforces a daily transaction allowance. Backoff
                    # helps with per-second throttling but not with a spent daily
                    # quota, so the message names both possibilities.
                    last_error = ProviderError(
                        "HERE returned 429. This is either per-second throttling or an "
                        f"exhausted daily allowance. Detail: {response.text[:200]}"
                    )
                    time.sleep(2**attempt)
                    continue
                if response.status_code in (500, 502, 503, 504):
                    last_error = ProviderError(f"HERE returned {response.status_code}: {response.text[:300]}")
                    time.sleep(2**attempt)
                    continue
                if response.status_code == 401:
                    raise ProviderError(
                        "HERE rejected the API key (401). Check HERE_API_KEY in backend/.env "
                        "and that the key is enabled for the Geocoding & Search service."
                    )
                if response.status_code >= 400:
                    raise ProviderError(f"HERE returned {response.status_code}: {response.text[:300]}")
                return response.json()
            except httpx.HTTPError as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise ProviderError(f"HERE request failed after retries: {last_error}")

    # --- mapping -----------------------------------------------------------

    @staticmethod
    def _categories(item: dict) -> list[str]:
        """Both IDs and names, because the classifier uses IDs first and names as fallback."""
        values: list[str] = []
        for category in item.get("categories") or []:
            for key in ("id", "name"):
                value = category.get(key)
                if value:
                    values.append(str(value))
        for chain in item.get("foodTypes") or []:
            name = chain.get("name")
            if name:
                values.append(str(name))
        return values

    @staticmethod
    def _phone(item: dict) -> str | None:
        for contact in item.get("contacts") or []:
            for entry in contact.get("phone") or []:
                value = entry.get("value")
                if value:
                    return str(value)
        return None

    @staticmethod
    def _website(item: dict) -> str | None:
        for contact in item.get("contacts") or []:
            for entry in contact.get("www") or []:
                value = entry.get("value")
                if value:
                    return str(value)
        return None

    def _to_dto(self, item: dict) -> ProviderPlaceDTO:
        position = item.get("position") or {}
        address = item.get("address") or {}
        return ProviderPlaceDTO(
            provider=Provider.HERE,
            provider_place_id=item.get("id") or "",
            name=item.get("title") or "",
            categories=self._categories(item),
            address=address.get("label"),
            city=address.get("city") or address.get("district"),
            province=address.get("state") or address.get("county"),
            postal_code=address.get("postalCode"),
            lat=position.get("lat"),
            lng=position.get("lng"),
            phone=self._phone(item),
            website=self._website(item),
            # HERE has no direct businessStatus equivalent on /browse.
            business_status=None,
            raw=item,
        )

    # --- operations --------------------------------------------------------

    def browse_tile(self, tile: Tile, category_root: str | None = None) -> SweepResult:
        """One /browse call over one tile, optionally filtered to a HERE category root."""
        params = {
            "at": f"{tile.lat},{tile.lng}",
            "in": f"circle:{tile.lat},{tile.lng};r={int(round(tile.radius_m))}",
            "limit": min(self.settings.here_max_results_per_call, BROWSE_MAX_LIMIT),
            "lang": self.settings.here_language,
        }
        if category_root:
            params["categories"] = category_root
        payload = self._get(BROWSE_URL, params)
        items = payload.get("items") or []
        return SweepResult(
            places=[self._to_dto(i) for i in items],
            api_calls=1,
            saturated=len(items) >= min(self.settings.here_max_results_per_call, BROWSE_MAX_LIMIT),
        )

    def sweep(self, tile: Tile) -> SweepResult:
        """Browse one tile once per HERE top-level category root, deduplicated by id.

        One unfiltered call would be cheaper but recalls far less: /browse caps at
        100 results, so in a dense block a single call comes back as 100 restaurants
        and nothing else. Sweeping per root is the same trade the Grab adapter makes
        with its keyword matrix — more calls, but coverage that is not silently
        truncated to whatever the provider ranked first.

        Saturation is reported if ANY root filled its page, so the sweep service
        subdivides the tile and re-runs the whole root set over the smaller circles.
        """
        from ..services.taxonomy import HERE_SWEEP_ROOTS

        by_id: dict[str, ProviderPlaceDTO] = {}
        total_calls = 0
        saturated = False
        for root in HERE_SWEEP_ROOTS:
            result = self.browse_tile(tile, root)
            total_calls += result.api_calls
            saturated = saturated or result.saturated
            for dto in result.places:
                if dto.provider_place_id:
                    by_id.setdefault(dto.provider_place_id, dto)
        return SweepResult(places=list(by_id.values()), api_calls=total_calls, saturated=saturated)

    def probe(self, name: str, lat: float, lng: float, address: str | None) -> SweepResult:
        """Targeted lookup used to prove a place is or is not in HERE."""
        query = " ".join(part for part in [name, address] if part).strip()
        payload = self._get(DISCOVER_URL, {
            "q": query[:250],
            "at": f"{lat},{lng}",
            "in": f"circle:{lat},{lng};r=500",
            "limit": 10,
            "lang": self.settings.here_language,
        })
        return SweepResult(places=[self._to_dto(i) for i in payload.get("items") or []], api_calls=1)
