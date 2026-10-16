"""GrabMaps adapter via Amazon Location Service (geo-places), ap-southeast-1.

Two constraints from the AWS API reference drive this design:

1. GrabMaps supports SearchText, Suggest, ReverseGeocode and GetPlace only. There is
   NO SearchNearby, so category-radius discovery is impossible. Discovery is instead a
   keyword matrix: each tile is searched once per Indonesian search term, with a
   circle filter restricting results to the tile. Recall on this provider is therefore
   bounded by the term list, which is why a Grab gap is weaker evidence than a Google
   or HERE gap.

2. In ap-southeast-1 / ap-southeast-5, GrabMaps supports only the `TimeZone` value for
   AdditionalFeatures. `Contact` is unavailable, so GrabMaps returns NO phone numbers
   and NO websites. The matching engine therefore cannot use contact signals across
   providers, and Grab-only records arrive with no contact channel at all.

Coordinates are GeoJSON [lng, lat] on the wire and are converted at this boundary.
"""
from __future__ import annotations

import re
import time

from ..config import get_settings
from ..models import Provider
from ..services.geo import Tile
from .base import ProviderError, ProviderPlaceDTO, SweepResult

def default_query_terms() -> list[str]:
    """Every search term in the unified taxonomy, across all categories.

    This is the whole of Grab's recall: a place whose name matches no term is
    invisible to this provider no matter how many tiles are swept. Widen the term
    matrix in services/taxonomy.py to trade cost for recall.
    """
    from ..services.taxonomy import GRAB_QUERY_TERMS

    terms: list[str] = []
    for values in GRAB_QUERY_TERMS.values():
        for term in values:
            if term not in terms:
                terms.append(term)
    return terms


_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

# Grab returns residential units as POIs whose *name* is their address, e.g.
# "Blok BI3 No.15 Perumahan Citra Utama 2" tagged as category "villa". In a live
# Jakarta sweep 383 of 1,167 records were these — a third of the dataset — and they
# inflated the Accommodation count to eight times what HERE reported for the same
# circle. They are houses, not businesses, and no other provider carries them, so
# every one became a false "only Grab has this" finding.
#
# Matched on the NAME, not the category: "villa" is a legitimate category for a real
# holiday villa, so vetoing the category would drop genuine accommodation too.
#: Street and estate words. A house number in front of one of these is an address.
_THOROUGHFARE = r"(?:jl\.?|jalan|gang|gg\.?|perumahan|komplek(?:s)?|blok)"

ADDRESS_NAME_RE = re.compile(
    r"^\s*(?:"
    # Starts with an address keyword: "Blok D No.6 ...", "Jalan Kramat", "RT 05 ...".
    r"blok\b|bloc\b|no\.?\s*\d|nomor\s*\d|" + _THOROUGHFARE + r"\b|rt\s*\d|rw\s*\d"
    r"|"
    # Starts with a house number followed by a street or estate word:
    # "14, Jl. Minangkabau", "6G, Jl. ...", "18 Perumahan Al Jazeera".
    # Deliberately requires the thoroughfare word, so businesses that merely begin
    # with a number — "99 Jaya Utama PT", "72 Kios", "3 Putri Toko" — are kept.
    r"\d+\s*[a-z]?\s*[,.]?\s*" + _THOROUGHFARE + r"\b"
    r")",
    re.IGNORECASE,
)


def looks_like_address(name: str | None) -> bool:
    """True when a Grab place name is a street address rather than a business name."""
    return bool(name and ADDRESS_NAME_RE.match(name))

PLACE_TYPES_KEPT = {"PointOfInterest", "PointAddress", "Street", "Locality"}
MAX_RESULTS_PER_CALL = 100  # API ceiling for SearchText


class GrabMapsAdapter:
    provider = Provider.GRAB

    def __init__(self, client=None):
        settings = get_settings()
        self.settings = settings
        self._api_key = settings.aws_location_api_key or None
        if client is not None:
            self._client = client
            return
        if not settings.grab_enabled:
            raise ProviderError(
                "GrabMaps is not configured: set AWS_LOCATION_API_KEY, or "
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
            )
        try:
            import boto3  # imported lazily so the rest of the app runs without boto3
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderError("boto3 is required for the GrabMaps adapter: pip install boto3") from exc

        if self._api_key:
            # An Amazon Location API key authenticates the request on its own, so the
            # request must go out unsigned — botocore would otherwise refuse to build
            # it without IAM credentials present.
            from botocore import UNSIGNED
            from botocore.config import Config

            self._client = boto3.client(
                "geo-places", region_name=settings.aws_region, config=Config(signature_version=UNSIGNED)
            )
            return

        kwargs = {
            "region_name": settings.aws_region,
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key,
        }
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
        self._client = boto3.client("geo-places", **kwargs)

    # --- mapping -----------------------------------------------------------

    @staticmethod
    def _category_names(item: dict) -> list[str]:
        names: list[str] = []
        for category in item.get("Categories") or []:
            for key in ("Name", "LocalizedName", "Id"):
                value = category.get(key)
                if value:
                    names.append(str(value))
        return names

    def _to_dto(self, item: dict) -> ProviderPlaceDTO:
        address = item.get("Address") or {}
        position = item.get("Position") or []
        # Position is GeoJSON order: [longitude, latitude].
        lng = position[0] if len(position) >= 2 else None
        lat = position[1] if len(position) >= 2 else None
        region = address.get("Region") or {}
        return ProviderPlaceDTO(
            provider=Provider.GRAB,
            provider_place_id=item.get("PlaceId") or "",
            name=item.get("Title") or "",
            categories=self._category_names(item),
            address=address.get("Label"),
            city=address.get("Locality") or address.get("District"),
            province=region.get("Name") or region.get("Code"),
            postal_code=address.get("PostalCode"),
            lat=lat,
            lng=lng,
            # GrabMaps cannot return Contacts in ap-southeast-1/5, so these stay None.
            phone=None,
            website=None,
            business_status=None,
            raw=item,
        )

    # --- transport ---------------------------------------------------------

    @staticmethod
    def _pricing_bucket(payload: dict) -> str | None:
        """Amazon Location reports the bucket it charged in a response header."""
        headers = (payload.get("ResponseMetadata") or {}).get("HTTPHeaders") or {}
        return headers.get("x-amz-geo-pricing-bucket")

    def _search_text(self, query: str, lat: float, lng: float, radius_m: float, max_results: int) -> tuple[list[dict], int, dict[str, int]]:
        """One paginated SearchText query. Returns (items, api_calls_made, buckets)."""
        items: list[dict] = []
        calls = 0
        buckets: dict[str, int] = {}
        next_token: str | None = None
        while True:
            request = {
                "QueryText": query[:200],
                "Filter": {
                    # Radius must be an integer: botocore rejects a float outright,
                    # client-side, before any request is sent.
                    "Circle": {"Center": [float(lng), float(lat)], "Radius": int(round(radius_m))},
                    "IncludeCountries": [self.settings.grab_country],
                },
                "MaxResults": int(min(max_results, MAX_RESULTS_PER_CALL)),
                "Language": self.settings.grab_language,
                "IntendedUse": self.settings.grab_intended_use,
            }
            if next_token:
                request["NextToken"] = next_token
            if self._api_key:
                request["Key"] = self._api_key
            last_error: Exception | None = None
            payload = None
            for attempt in range(self.settings.provider_max_retries):
                try:
                    payload = self._client.search_text(**request)
                    calls += 1
                    break
                except Exception as exc:  # botocore raises ClientError subclasses
                    last_error = exc
                    if _is_throttle(exc) and attempt < self.settings.provider_max_retries - 1:
                        time.sleep(2**attempt)
                        continue
                    raise ProviderError(f"GrabMaps SearchText failed: {exc}") from exc
            if payload is None:  # pragma: no cover - defensive
                raise ProviderError(f"GrabMaps SearchText failed: {last_error}")

            bucket = self._pricing_bucket(payload)
            if bucket:
                buckets[bucket] = buckets.get(bucket, 0) + 1

            items.extend(payload.get("ResultItems") or [])
            next_token = payload.get("NextToken")
            if not next_token or len(items) >= max_results:
                break
        return items, calls, buckets

    # --- operations --------------------------------------------------------

    def sweep(
        self,
        tile: Tile,
        terms: list[str] | None = None,
        place_types: set[str] | None = None,
    ) -> SweepResult:
        """Keyword matrix over one tile, deduplicated by PlaceId.

        Defaults to the full taxonomy term matrix, which is the only way to
        approximate "every POI in this circle" on a provider with no SearchNearby.

        `place_types` narrows what counts as a result. The default keeps addresses
        and streets, which the city job relies on. The area comparison passes
        {"PointOfInterest"} instead, because SearchText answers a keyword query with
        whatever it can geocode: a live "rumah sakit" query in Denpasar came back
        with villas and multi-family homes, and every one of those would have become
        a spurious "only Grab has it" finding.
        """
        keep_types = place_types or PLACE_TYPES_KEPT
        by_id: dict[str, ProviderPlaceDTO] = {}
        total_calls = 0
        saturated = False
        all_buckets: dict[str, int] = {}
        for term in (terms or default_query_terms()):
            items, calls, buckets = self._search_text(term, tile.lat, tile.lng, tile.radius_m, MAX_RESULTS_PER_CALL)
            total_calls += calls
            for name, count in buckets.items():
                all_buckets[name] = all_buckets.get(name, 0) + count
            if len(items) >= MAX_RESULTS_PER_CALL:
                saturated = True
            for item in items:
                if item.get("PlaceType") and item["PlaceType"] not in keep_types:
                    continue
                # Residential units whose name is an address are not businesses.
                if looks_like_address(item.get("Title")):
                    continue
                dto = self._to_dto(item)
                if dto.provider_place_id:
                    by_id.setdefault(dto.provider_place_id, dto)
        return SweepResult(
            places=list(by_id.values()),
            api_calls=total_calls,
            saturated=saturated,
            pricing_buckets=all_buckets,
        )

    def probe(self, name: str, lat: float, lng: float, address: str | None) -> SweepResult:
        query = " ".join(part for part in [name, address] if part).strip()
        items, calls, buckets = self._search_text(query, lat, lng, 500.0, 10)
        return SweepResult(
            places=[self._to_dto(i) for i in items], api_calls=calls, pricing_buckets=buckets
        )


def _is_throttle(exc: Exception) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "") if hasattr(exc, "response") else ""
    return code in {"ThrottlingException", "TooManyRequestsException", "InternalServerException"}


def category_tokens(categories: list[str]) -> set[str]:
    return {t for t in _TOKEN_SPLIT.split(" ".join(categories).lower()) if t}


def _hierarchy_paths(categories: list[str]) -> list[str]:
    """Category entries that carry taxonomy position, i.e. contain a '::' separator."""
    return [c.lower().strip() for c in categories if "::" in c]


