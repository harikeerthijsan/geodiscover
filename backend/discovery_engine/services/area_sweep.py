"""Sweep one user-drawn circle across HERE, Google and Grab, then compare.

This is the orchestrator behind the three-map comparison. It differs from the
city discovery job in three ways that matter:

  * All categories, not one vertical. Each provider gets a *sweep plan* — a list of
    query units to issue per tile — derived from the shared taxonomy.
  * Three providers, not two, resolved by clustering rather than pairing.
  * The area is drawn by the user rather than derived from a city record.

Cost shape, which is worth understanding before running one:

    Google calls ≈ tiles x category groups   (13 groups by default)
    Grab   calls ≈ tiles x keyword terms     (~60 terms by default)
    HERE   calls ≈ tiles x category roots    (10 roots)

A 3 km circle at the default 400 m tile radius is roughly 60 tiles before any
subdivision, so Google alone starts near 800 calls and Grab near 3,600. The
per-provider caps and the USD ceilings are what stop a dense area from running
away; a provider that hits either is recorded in `partial_providers` so partial
coverage is never presented as complete.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    AreaCluster,
    AreaSweep,
    Provider,
    ProviderPlace,
    RunStatus,
    utcnow,
)
from ..providers import ProviderError, get_adapter
from ..services.geo import Tile, cover_circle_with_tiles, haversine_m
from ..services.pricing import cost_of, rate_for, summarise, sweep_operation
from ..services.sweep import MIN_TILE_RADIUS_M, upsert_place
from ..services.taxonomy import (
    CATEGORY_LABELS,
    CORE_CATEGORIES,
    ORDERED_CATEGORIES,
    UnifiedCategory,
    google_sweep_plan,
    grab_sweep_plan,
    here_sweep_plan,
)
from ..services.three_way import build_clusters, summarise_buckets, summarise_categories

DEFAULT_RADIUS_M = 3000.0
DEFAULT_TILE_RADIUS_M = 400.0
ALL_PROVIDERS = [Provider.HERE, Provider.GOOGLE, Provider.GRAB]


#: Commit at least this often during a sweep leg.
#
# SQLite holds a write lock for the life of a transaction, so a sweep that only
# commits at the end blocks every read for its whole run — the status endpoint
# stops answering and the interface's progress polling hangs until the sweep
# finishes. Committing periodically keeps progress visible, and a partially
# completed sweep is a legitimate state here anyway: a leg that stops at its
# budget cap is recorded and reported, never rolled back.
CHECKPOINT_EVERY_CALLS = 25


def _checkpoint(db: Session) -> None:
    """Release the write lock so pollers can read progress."""
    db.commit()


def mark_interrupted_sweeps(db: Session) -> int:
    """Close out sweeps left mid-flight by a restart. Returns how many were closed.

    A sweep runs in a background task inside the web process, so stopping the server
    kills it with the row still reading RUNNING. Nothing resumes it, so the row would
    otherwise sit at RUNNING forever and the interface would poll it indefinitely.

    The places it already collected are kept — they were paid for and are real — and
    the sweep is marked ABORTED_BUDGET, which the interface already renders as partial
    coverage. Calling this at startup is safe because no sweep can survive a restart.
    """
    stale = db.scalars(
        select(AreaSweep).where(AreaSweep.status.in_([RunStatus.RUNNING, RunStatus.PENDING]))
    ).all()
    for sweep in stale:
        sweep.status = RunStatus.ABORTED_BUDGET
        sweep.stage = "INTERRUPTED"
        sweep.error = (
            "Interrupted: the server stopped while this sweep was running. Records "
            "already collected are kept, but coverage is incomplete. Re-run to finish."
        )
        sweep.finished_at = utcnow()
        if not sweep.partial_providers:
            sweep.partial_providers = list(sweep.providers or [])
    if stale:
        db.commit()
    return len(stale)


def _categories_from(values: list[str] | None) -> list[UnifiedCategory] | None:
    """Parse stored category strings; None means every category."""
    if not values:
        return None
    parsed = []
    for value in values:
        try:
            parsed.append(UnifiedCategory(value))
        except ValueError:
            continue
    return parsed or None


def _calls_per_tile(provider: Provider, categories: list[UnifiedCategory] | None) -> int:
    if provider == Provider.GOOGLE:
        return len(google_sweep_plan(categories))
    if provider == Provider.GRAB:
        return len(grab_sweep_plan(categories))
    return len(here_sweep_plan(categories))


def estimate_area_sweep(
    center_lat: float,
    center_lng: float,
    radius_m: float = DEFAULT_RADIUS_M,
    tile_radius_m: float = DEFAULT_TILE_RADIUS_M,
    categories: list[str] | None = None,
    providers: list[str] | None = None,
    saturation_allowance: float = 1.35,
) -> dict:
    """Pre-flight cost estimate, shown to the user before anything is spent."""
    settings = get_settings()
    parsed = _categories_from(categories)
    wanted = [Provider(p) for p in providers] if providers else list(ALL_PROVIDERS)
    tiles = cover_circle_with_tiles(center_lat, center_lng, radius_m, tile_radius_m)

    lines = []
    total_expected = 0.0
    any_unpriced = False
    for provider in wanted:
        per_tile = _calls_per_tile(provider, parsed)
        base = len(tiles) * per_tile
        expected = int(round(base * saturation_allowance))
        operation = sweep_operation(provider)
        expected_cost = summarise({operation: expected}, settings)
        cap = _call_cap(provider, settings)
        if expected_cost["cost_usd"] is not None:
            total_expected += expected_cost["cost_usd"]
        else:
            any_unpriced = True
        lines.append({
            "provider": provider.value,
            "tiles": len(tiles),
            "calls_per_tile": per_tile,
            "calls_minimum": base,
            "calls_expected": expected,
            "calls_cap": cap,
            "cost_expected_usd": expected_cost["cost_usd"],
            "rate_per_1k_usd": rate_for(operation, settings),
            "configured": provider_configured(provider, settings),
            "note": _provider_note(provider),
        })

    return {
        "center": {"lat": center_lat, "lng": center_lng},
        "radius_m": radius_m,
        "tile_radius_m": tile_radius_m,
        "tiles": len(tiles),
        "categories": [c.value for c in (parsed or ORDERED_CATEGORIES) if c is not UnifiedCategory.OTHER],
        "providers": lines,
        "cost_expected_total_usd": round(total_expected, 2),
        "cost_is_complete": not any_unpriced,
        "saturation_allowance": saturation_allowance,
        "note": (
            "Expected cost assumes the configured per-1,000 rates are right for your "
            "billing tier and includes a 35% allowance for tile subdivision in dense "
            "areas. The per-provider call caps are the only hard bound on spend."
        ),
    }


def provider_configured(provider: Provider, settings=None) -> bool:
    """True when this provider has credentials and can actually be swept."""
    settings = settings or get_settings()
    if provider == Provider.HERE:
        return settings.here_enabled
    if provider == Provider.GOOGLE:
        return settings.google_enabled
    return settings.grab_enabled


def _provider_note(provider: Provider) -> str:
    if provider == Provider.HERE:
        return "HERE /browse, one call per category root per tile, 100 results per call."
    if provider == Provider.GOOGLE:
        return (
            "Google searchNearby, one call per category group per tile. Capped at 20 "
            "results per call, so dense tiles subdivide and cost more than the minimum."
        )
    return (
        "Grab has no radius search, only SearchText, so coverage is keyword-derived: "
        "one call per search term per tile. A Grab gap is weaker evidence than a "
        "Google or HERE gap."
    )


def _call_cap(provider: Provider, settings) -> int:
    if provider == Provider.GOOGLE:
        return settings.google_max_calls_per_run
    if provider == Provider.HERE:
        return settings.here_max_calls_per_run
    return settings.grab_max_calls_per_run


def _spend_cap(provider: Provider, settings) -> float:
    if provider == Provider.GOOGLE:
        return settings.google_max_spend_per_run_usd
    if provider == Provider.HERE:
        return 0.0  # HERE freemium is allowance-bound, not spend-bound
    return settings.grab_max_spend_per_run_usd


def _sweep_one_tile(adapter, provider: Provider, tile: Tile, unit):
    """Issue one provider-shaped query unit against one tile."""
    if provider == Provider.GOOGLE:
        _, included_types = unit
        return adapter.sweep(tile, included_types)
    if provider == Provider.GRAB:
        _, term = unit
        # POIs only. SearchText otherwise answers with geocoded addresses, which are
        # not places any map "has" and would read as Grab-exclusive findings.
        return adapter.sweep(tile, [term], place_types={"PointOfInterest"})
    return adapter.browse_tile(tile, unit)


def _record_leg_progress(db: Session, sweep: AreaSweep, provider: Provider, calls: int, found: int) -> None:
    """Publish in-flight counts for one leg, then commit so pollers can see them."""
    breakdown = dict(sweep.cost_breakdown or {})
    leg = dict(breakdown.get(provider.value) or {})
    leg.update({"provider": provider.value, "api_calls": calls, "places_found": found, "in_flight": True})
    breakdown[provider.value] = leg
    sweep.cost_breakdown = breakdown
    sweep.api_calls = sum(
        v.get("api_calls", 0) for v in breakdown.values() if isinstance(v, dict)
    )
    _checkpoint(db)


def _sweep_provider(
    db: Session,
    sweep: AreaSweep,
    provider: Provider,
    categories: list[UnifiedCategory] | None,
) -> dict:
    """Sweep every tile x query-unit for one provider, subdividing saturated tiles."""
    settings = get_settings()
    operation = sweep_operation(provider)
    rate = rate_for(operation, settings)
    max_calls = _call_cap(provider, settings)
    max_spend = _spend_cap(provider, settings)

    if provider == Provider.GOOGLE:
        units = google_sweep_plan(categories)
    elif provider == Provider.GRAB:
        units = grab_sweep_plan(categories)
    else:
        units = here_sweep_plan(categories)

    adapter = get_adapter(provider)

    calls = 0
    found = 0
    last_checkpoint = 0
    saturated_tiles = 0
    partial = False
    error: str | None = None

    try:
        # Each query unit gets its own tile queue, because saturation is a property
        # of (tile, unit): "restaurants" can saturate a block that "embassies" does
        # not, and subdividing for both would multiply cost for no extra recall.
        for unit in units:
            queue: list[Tile] = cover_circle_with_tiles(
                sweep.center_lat, sweep.center_lng, sweep.radius_m, sweep.tile_radius_m
            )
            while queue:
                if calls >= max_calls:
                    partial = True
                    error = f"Stopped at the {max_calls} call cap with {len(queue)} tiles queued"
                    break
                spent = cost_of(operation, calls, settings).cost_usd
                if max_spend > 0 and rate is not None and spent is not None and spent >= max_spend:
                    partial = True
                    error = f"Stopped at the ${max_spend:.2f} ceiling after {calls} calls"
                    break

                tile = queue.pop(0)
                result = _sweep_one_tile(adapter, provider, tile, unit)
                calls += result.api_calls
                found += len(result.places)

                for dto in result.places:
                    if not dto.provider_place_id:
                        continue
                    upsert_place(
                        db, sweep.project_id, None, dto, area_sweep_id=sweep.id
                    )

                if result.saturated and tile.radius_m / 2 >= MIN_TILE_RADIUS_M:
                    saturated_tiles += 1
                    queue.extend(tile.subdivide())
                elif result.saturated:
                    saturated_tiles += 1

                db.flush()
                if calls - last_checkpoint >= CHECKPOINT_EVERY_CALLS:
                    _record_leg_progress(db, sweep, provider, calls, found)
                    last_checkpoint = calls
            if partial:
                break
    except ProviderError as exc:
        error = str(exc)[:1000]
        partial = True
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()

    return {
        "provider": provider.value,
        "api_calls": calls,
        "places_found": found,
        "saturated_tiles": saturated_tiles,
        "cost_usd": cost_of(operation, calls, settings).cost_usd,
        "partial": partial,
        "error": error,
    }


def execute_area_sweep(db: Session, sweep: AreaSweep) -> AreaSweep:
    """Run the full three-provider sweep and comparison for one area.

    Any provider that fails outright is recorded and the run continues: two maps
    compared is a usable result, and losing the Grab leg should not discard an
    already-paid-for Google sweep.
    """
    settings = get_settings()
    categories = _categories_from(sweep.categories)
    providers = [Provider(p) for p in (sweep.providers or [p.value for p in ALL_PROVIDERS])]

    sweep.status = RunStatus.RUNNING
    sweep.started_at = utcnow()
    _checkpoint(db)

    breakdown: dict[str, dict] = {}
    partial: list[str] = []
    total_calls = 0
    total_cost = 0.0
    cost_complete = True

    for provider in providers:
        sweep.stage = f"SWEEPING_{provider.value}"
        _checkpoint(db)
        try:
            result = _sweep_provider(db, sweep, provider, categories)
        except Exception as exc:  # noqa: BLE001 - one dead leg must not kill the run
            result = {
                "provider": provider.value, "api_calls": 0, "places_found": 0,
                "saturated_tiles": 0, "cost_usd": 0.0,
                "partial": True, "error": str(exc)[:1000],
            }
        breakdown[provider.value] = result
        total_calls += result["api_calls"]
        if result["cost_usd"] is None:
            cost_complete = False
        else:
            total_cost += result["cost_usd"]
        if result["partial"]:
            partial.append(provider.value)
        db.flush()

    resolve_area_sweep(db, sweep, providers)

    sweep.api_calls = total_calls
    sweep.cost_breakdown = {**breakdown, "contested_edges": sweep.cost_breakdown.get("contested_edges", [])}
    sweep.actual_cost_usd = round(total_cost, 4) if cost_complete else None
    sweep.partial_providers = partial
    sweep.status = RunStatus.ABORTED_BUDGET if partial else RunStatus.COMPLETED
    sweep.finished_at = utcnow()
    db.flush()
    _checkpoint(db)
    return sweep


def resolve_area_sweep(db: Session, sweep: AreaSweep, providers: list[Provider] | None = None) -> AreaSweep:
    """Cluster a sweep's stored places into presence buckets. Calls no provider API.

    Split out of the sweep so a run can be re-resolved after a classification or
    filtering fix — the expensive part is the harvesting, and that is already paid for.
    """
    settings = get_settings()
    categories = _categories_from(sweep.categories)
    providers = providers or [Provider(p) for p in (sweep.providers or [])]

    sweep.stage = "MATCHING"
    _checkpoint(db)

    places_by_provider: dict[Provider, list] = {}
    for provider in providers:
        rows = db.scalars(
            select(ProviderPlace).where(
                ProviderPlace.area_sweep_id == sweep.id,
                ProviderPlace.provider == provider,
                # in_scope is the scope gate: it excludes records outside the requested
                # categories and provider artefacts such as Grab's address-named
                # residential units, which are not businesses any map "has".
                ProviderPlace.in_scope.is_(True),
                ProviderPlace.lat.is_not(None),
                ProviderPlace.lng.is_not(None),
            )
        ).all()
        # Two trims, both for the same reason: only compare what every provider was
        # actually asked for. Anything else manufactures a coverage gap.
        #
        #  1. Geometry. A boundary tile overlaps the edge of the circle, so each
        #     provider returns some places outside it.
        #  2. Category. HERE's category roots are coarser than the unified set — the
        #     roots that contain Healthcare also contain all of Retail — so a
        #     narrowed run collects far more from HERE than from Google or Grab. Left
        #     unfiltered, a two-category run reported 714 HERE-only places that were
        #     really shops the other two were never queried about.
        wanted = {c.value for c in categories} if categories else None
        places_by_provider[provider] = [
            row for row in rows
            if haversine_m(sweep.center_lat, sweep.center_lng, row.lat, row.lng) <= sweep.radius_m
            and (wanted is None or row.unified_category in wanted)
        ]

    clusters, contested = build_clusters(
        places_by_provider,
        auto_threshold=settings.match_auto_threshold,
        possible_threshold=settings.match_possible_threshold,
        max_distance_m=settings.match_max_distance_m,
    )

    # Replace any previous result for this sweep so a re-run is idempotent.
    for stale in db.scalars(select(AreaCluster).where(AreaCluster.sweep_id == sweep.id)).all():
        db.delete(stale)
    db.flush()

    for cluster in clusters:
        identity = cluster.identity
        db.add(AreaCluster(
            sweep_id=sweep.id,
            project_id=sweep.project_id,
            bucket=cluster.bucket,
            unified_category=cluster.unified_category,
            display_name=(identity.name if identity else "")[:255],
            address=identity.address if identity else None,
            lat=identity.lat if identity else None,
            lng=identity.lng if identity else None,
            here_place_id=getattr(cluster.members.get(Provider.HERE), "id", None),
            google_place_id=getattr(cluster.members.get(Provider.GOOGLE), "id", None),
            grab_place_id=getattr(cluster.members.get(Provider.GRAB), "id", None),
            match_evidence=cluster.evidence,
            max_pair_distance_m=cluster.max_pair_distance_m,
        ))

    sweep.provider_counts = {p.value: len(places_by_provider.get(p, [])) for p in providers}
    sweep.bucket_counts = summarise_buckets(clusters)
    sweep.category_matrix = summarise_categories(clusters)
    sweep.clusters_total = len(clusters)
    breakdown = dict(sweep.cost_breakdown or {})
    breakdown["contested_edges"] = contested[:200]
    sweep.cost_breakdown = breakdown
    sweep.stage = "FINISHED"
    db.flush()
    _checkpoint(db)
    return sweep


def category_options() -> list[dict]:
    """Category list for the interface, excluding the OTHER catch-all.

    `core` marks the seven categories this deployment normally runs, so the
    interface can offer them as a one-click preset without hardcoding the list.
    """
    core = set(CORE_CATEGORIES)
    return [
        {
            "value": category.value,
            "label": CATEGORY_LABELS[category],
            "core": category in core,
        }
        for category in ORDERED_CATEGORIES
        if category is not UnifiedCategory.OTHER
    ]
