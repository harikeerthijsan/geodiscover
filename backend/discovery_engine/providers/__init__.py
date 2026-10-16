from ..models import Provider
from .base import BudgetExceeded, ProviderAdapter, ProviderError, ProviderPlaceDTO, SweepResult


def get_adapter(provider: Provider) -> ProviderAdapter:
    """Build the adapter for a provider. Imports are local so a missing optional
    dependency (boto3) only breaks the provider that needs it."""
    if provider == Provider.GOOGLE:
        from .google import GooglePlacesAdapter

        return GooglePlacesAdapter()
    if provider == Provider.GRAB:
        from .grab import GrabMapsAdapter

        return GrabMapsAdapter()
    if provider == Provider.HERE:
        from .here import HereAdapter

        return HereAdapter()
    raise ProviderError(f"Unknown provider: {provider}")


__all__ = [
    "BudgetExceeded",
    "ProviderAdapter",
    "ProviderError",
    "ProviderPlaceDTO",
    "SweepResult",
    "get_adapter",
]
