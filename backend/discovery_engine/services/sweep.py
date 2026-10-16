"""Metered, budget-capped discovery sweeps with adaptive tile subdivision."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import DiscoveryRun, Provider, ProviderPlace, RunStatus, SearchArea, utcnow
from ..providers import ProviderAdapter, ProviderPlaceDTO
from ..services.geo import Tile, cover_circle_with_tiles
from ..services.pricing import cost_of, estimate_sweep, rate_for, sweep_operation
from ..services.normalization import (
    match_name,
    normalize_phone_id,
    normalize_text,
    website_domain,
)
from ..services.taxonomy import classify

DEFAULT_TILE_RADIUS_M = 400.0
MIN_TILE_RADIUS_M = 100.0


def _in_scope(dto: ProviderPlaceDTO, categories: set[str] | None) -> bool:
    """Scope gate: is this place one of the categories the run asked for?

    `categories` holds UnifiedCategory values. None means no filter, so every place
    is in scope — which is the correct default for a general POI sweep.

    Classification is the provider's own taxonomy folded onto the shared one, so a
    hospital is a hospital whether Google called it `hospital`, HERE called it
    `800-8000-0159`, or Grab called it `healthcare::hospital`.
    """
    if not categories:
        return True
    return classify(dto.provider.value, dto.categories, dto.name).value in categories


def upsert_place(
    db: Session,
    project_id: int,
    run_id: int | None,
    dto: ProviderPlaceDTO,
    job_id: int | None = None,
    area_sweep_id: int | None = None,
    categories: set[str] | None = None,
) -> tuple[ProviderPlace, bool]:
    """Insert or refresh a provider place. Returns (row, created)."""
    settings = get_settings()
    existing = db.scalar(
        select(ProviderPlace).where(
            ProviderPlace.project_id == project_id,
            ProviderPlace.provider == dto.provider,
            ProviderPlace.provider_place_id == dto.provider_place_id,
        )
    )
    expires = datetime.now(timezone.utc) + timedelta(days=settings.provider_payload_ttl_days)
    fields = dict(
        raw_payload=dto.raw,
        payload_expires_at=expires,
        name=dto.name,
        normalized_name=normalize_text(dto.name),
        match_name=match_name(dto.name),
        categories=dto.categories,
        in_scope=_in_scope(dto, categories),
        # Computed for every place, not just area sweeps: the city job's exports get
        # a comparable category for free, and a row written by either path classifies
        # the same way.
        unified_category=classify(dto.provider.value, dto.categories, dto.name).value,
        address=dto.address,
        city=dto.city,
        province=dto.province,
        postal_code=dto.postal_code,
        lat=dto.lat,
        lng=dto.lng,
        phone_e164=normalize_phone_id(dto.phone),
        website=dto.website,
        website_domain=website_domain(dto.website),
        business_status=dto.business_status,
    )
    if existing:
        for key, value in fields.items():
            setattr(existing, key, value)
        if job_id is not None and existing.job_id is None:
            existing.job_id = job_id
        # Re-stamped on every sweep: the same place found again by a later area sweep
        # belongs to that comparison too, and the newest run is the relevant scope.
        if area_sweep_id is not None:
            existing.area_sweep_id = area_sweep_id
        existing.last_seen_at = utcnow()
        return existing, False

    place = ProviderPlace(
        project_id=project_id,
        run_id=run_id,
        job_id=job_id,
        area_sweep_id=area_sweep_id,
        provider=dto.provider,
        provider_place_id=dto.provider_place_id,
        **fields,
    )
    db.add(place)
    return place, True


def run_sweep(
    db: Session,
    run: DiscoveryRun,
    adapter: ProviderAdapter,
    areas: list[SearchArea],
    tile_radius_m: float = DEFAULT_TILE_RADIUS_M,
    max_calls: int | None = None,
    job_id: int | None = None,
    max_spend_usd: float | None = None,
    categories: set[str] | None = None,
) -> DiscoveryRun:
    """Sweep every area, subdividing any tile that comes back saturated.

    A saturated tile means the provider hit its result ceiling and may be hiding
    places, so the tile is split into four smaller circles and re-swept. Without this,
    dense commercial blocks silently under-report and the whole comparison is skewed
    toward false "unique" records.
    """
    settings = get_settings()
    is_google = run.provider == Provider.GOOGLE
    if max_calls is None:
        max_calls = settings.google_max_calls_per_run if is_google else settings.grab_max_calls_per_run
    # A caller running a multi-stage job passes the budget still remaining, so the
    # stages share one ceiling instead of each getting a fresh one.
    max_spend = (
        max_spend_usd if max_spend_usd is not None
        else (settings.google_max_spend_per_run_usd if is_google else settings.grab_max_spend_per_run_usd)
    )
    operation = sweep_operation(run.provider)
    rate = rate_for(operation, settings)

    queue: list[Tile] = []
    for area in areas:
        queue.extend(cover_circle_with_tiles(area.center_lat, area.center_lng, area.radius_m, tile_radius_m))

    run.status = RunStatus.RUNNING
    run.tiles_planned = len(queue)
    run.est_cost_usd = estimate_sweep(run.provider, len(queue), settings)["cost_expected_usd"]
    db.flush()

    found = 0
    kept = 0
    try:
        while queue:
            if run.api_calls >= max_calls:
                run.status = RunStatus.ABORTED_BUDGET
                run.error = f"Stopped at the {max_calls} call cap with {len(queue)} tiles still queued"
                break

            # A spend ceiling can only be enforced when the rate is known. An
            # unconfigured rate must not silently read as "$0 spent, keep going".
            if max_spend > 0 and rate is not None and (run.actual_cost_usd or 0.0) >= max_spend:
                run.status = RunStatus.ABORTED_BUDGET
                run.error = (
                    f"Stopped at the ${max_spend:.2f} spend ceiling after "
                    f"{run.api_calls} calls with {len(queue)} tiles still queued"
                )
                break

            tile = queue.pop(0)
            result = adapter.sweep(tile)
            run.api_calls += result.api_calls
            run.tiles_done += 1
            found += len(result.places)

            counts = dict(run.call_counts or {})
            counts[operation] = counts.get(operation, 0) + result.api_calls
            run.call_counts = counts
            run.actual_cost_usd = cost_of(operation, counts[operation], settings).cost_usd

            if result.pricing_buckets:
                buckets = dict(run.pricing_buckets or {})
                for name, count in result.pricing_buckets.items():
                    buckets[name] = buckets.get(name, 0) + count
                run.pricing_buckets = buckets

            for dto in result.places:
                if not dto.provider_place_id:
                    continue
                place, _ = upsert_place(
                    db, run.project_id, run.id, dto, job_id=job_id, categories=categories
                )
                if place.in_scope:
                    kept += 1

            if result.saturated and tile.radius_m / 2 >= MIN_TILE_RADIUS_M:
                run.saturated_tiles += 1
                children = tile.subdivide()
                queue.extend(children)
                run.tiles_planned += len(children)
            elif result.saturated:
                # At the floor radius and still saturated: record it rather than
                # pretending the tile was fully covered.
                run.saturated_tiles += 1

            db.flush()
        else:
            run.status = RunStatus.COMPLETED
    except Exception as exc:  # noqa: BLE001 - the run row is the error report
        run.status = RunStatus.FAILED
        run.error = str(exc)[:2000]

    run.places_found = found
    run.places_kept = kept
    run.finished_at = utcnow()
    db.flush()
    return run
