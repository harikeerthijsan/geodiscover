"""Provider-agnostic place shape and adapter contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import Provider
from ..services.geo import Tile


class ProviderError(RuntimeError):
    """Raised when a provider call fails after retries."""


class BudgetExceeded(RuntimeError):
    """Raised when a run would exceed its configured API call cap."""


@dataclass
class ProviderPlaceDTO:
    """One place from one provider, before it is persisted."""

    provider: Provider
    provider_place_id: str
    name: str
    categories: list[str] = field(default_factory=list)
    address: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    lat: float | None = None
    lng: float | None = None
    phone: str | None = None
    website: str | None = None
    business_status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SweepResult:
    places: list[ProviderPlaceDTO]
    api_calls: int
    saturated: bool = False
    """True when the tile hit the provider's result ceiling and may be hiding places."""
    pricing_buckets: dict[str, int] = field(default_factory=dict)
    """Pricing bucket the provider reports having charged, keyed by name to call count.
    Amazon Location supplies this in the x-amz-geo-pricing-bucket response header;
    Google does not expose an equivalent, so it stays empty there."""


class ProviderAdapter(Protocol):
    provider: Provider

    def sweep(self, tile: Tile) -> SweepResult:
        """Discover places inside a tile."""

    def probe(self, name: str, lat: float, lng: float, address: str | None) -> SweepResult:
        """Targeted lookup used to prove presence or absence of one specific place."""
