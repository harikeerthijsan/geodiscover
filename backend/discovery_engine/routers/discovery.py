"""Search areas, metered provider sweeps, bulk matching and reciprocal probes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..config import get_settings
from ..database import SessionLocal, get_db
from ..models import (
    DiscoveryRun,
    Project,
    Provider,
    RunStatus,
    SearchArea,
    User,
    UserRole,
    utcnow,
)
from ..providers import ProviderError, get_adapter
from ..schemas import (
    DiscoveryRunOut,
    ProbeRequest,
    SearchAreaCreate,
    SearchAreaOut,
    SweepRequest,
)
from ..services.audit import write_audit
from ..services.geo import cover_circle_with_tiles
from ..services.pricing import estimate_sweep, summarise, sweep_operation
from ..services.probe import probe_place, run_bulk_match, unprobed_places
from ..services.sweep import run_sweep

router = APIRouter(prefix="/discovery", tags=["Discovery"])

WRITE_ROLES = (UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST)


@router.post("/areas", response_model=SearchAreaOut, status_code=201)
def create_area(
    payload: SearchAreaCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES))],
):
    if not db.get(Project, payload.project_id):
        raise HTTPException(404, "Project not found")
    area = SearchArea(**payload.model_dump())
    db.add(area)
    db.flush()
    write_audit(db, user, "SEARCH_AREA_CREATED", "search_area", area.id, payload.model_dump())
    db.commit()
    db.refresh(area)
    return area


@router.get("/areas", response_model=list[SearchAreaOut])
def list_areas(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES, UserRole.QA_REVIEWER, UserRole.AUDITOR, UserRole.CUSTOMER_VIEWER))],
):
    return list(db.scalars(select(SearchArea).where(SearchArea.project_id == project_id).order_by(SearchArea.city, SearchArea.name)).all())


@router.post("/sweeps/estimate")
def estimate_sweep_cost(
    payload: SweepRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES, UserRole.QA_REVIEWER, UserRole.AUDITOR))],
):
    """Pre-flight cost estimate. Spends nothing — run this before every sweep."""
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    area_query = select(SearchArea).where(SearchArea.project_id == project.id, SearchArea.is_active.is_(True))
    if payload.area_ids:
        area_query = area_query.where(SearchArea.id.in_(payload.area_ids))
    areas = list(db.scalars(area_query).all())
    if not areas:
        raise HTTPException(400, "No active search areas for this project — define one first")

    tiles = 0
    per_area = []
    for area in areas:
        area_tiles = len(cover_circle_with_tiles(area.center_lat, area.center_lng, area.radius_m, payload.tile_radius_m))
        tiles += area_tiles
        per_area.append({"area_id": area.id, "city": area.city, "name": area.name,
                         "radius_m": area.radius_m, "tiles": area_tiles})

    estimate = estimate_sweep(payload.provider, tiles, get_settings())
    estimate["areas"] = per_area
    if payload.max_calls:
        estimate["calls_cap"] = min(estimate["calls_cap"], payload.max_calls)
        estimate["cost_at_cap_usd"] = summarise(
            {sweep_operation(payload.provider): estimate["calls_cap"]}, get_settings()
        )["cost_usd"]
    return estimate


@router.get("/costs/{project_id}")
def project_costs(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES, UserRole.QA_REVIEWER, UserRole.AUDITOR))],
):
    """Spend to date for a project, by provider and by run."""
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    settings = get_settings()
    runs = list(db.scalars(select(DiscoveryRun).where(DiscoveryRun.project_id == project_id).order_by(DiscoveryRun.id)).all())

    totals: dict[str, int] = {}
    by_provider: dict[str, dict[str, int]] = {}
    buckets: dict[str, int] = {}
    for run in runs:
        for operation, calls in (run.call_counts or {}).items():
            totals[operation] = totals.get(operation, 0) + calls
            by_provider.setdefault(run.provider.value, {})
            by_provider[run.provider.value][operation] = by_provider[run.provider.value].get(operation, 0) + calls
        for name, count in (run.pricing_buckets or {}).items():
            buckets[name] = buckets.get(name, 0) + count

    return {
        "project_id": project_id,
        "overall": summarise(totals, settings),
        "by_provider": {p: summarise(ops, settings) for p, ops in by_provider.items()},
        "provider_reported_pricing_buckets": buckets,
        "runs": [
            {
                "run_id": run.id,
                "provider": run.provider.value,
                "status": run.status.value,
                "api_calls": run.api_calls,
                "est_cost_usd": run.est_cost_usd,
                "actual_cost_usd": run.actual_cost_usd,
                "tiles_done": run.tiles_done,
                "tiles_planned": run.tiles_planned,
                "saturated_tiles": run.saturated_tiles,
            }
            for run in runs
        ],
        "rates_configured": {
            "google_nearby_per_1k": settings.rate_google_nearby_per_1k,
            "google_text_per_1k": settings.rate_google_text_per_1k,
            "google_details_per_1k": settings.rate_google_details_per_1k,
            "grab_search_text_per_1k": settings.rate_grab_search_text_per_1k,
        },
        "caps": {
            "google_max_calls_per_run": settings.google_max_calls_per_run,
            "grab_max_calls_per_run": settings.grab_max_calls_per_run,
            "google_max_spend_per_run_usd": settings.google_max_spend_per_run_usd,
            "grab_max_spend_per_run_usd": settings.grab_max_spend_per_run_usd,
        },
        "warning": (
            "Figures are computed from the configured rates, not from provider billing. "
            "Treat your Google Cloud billing console and AWS Cost Explorer as authoritative."
        ),
    }


@router.post("/sweeps", response_model=DiscoveryRunOut, status_code=202)
def start_sweep(
    payload: SweepRequest,
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES))],
):
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    area_query = select(SearchArea).where(SearchArea.project_id == project.id, SearchArea.is_active.is_(True))
    if payload.area_ids:
        area_query = area_query.where(SearchArea.id.in_(payload.area_ids))
    areas = list(db.scalars(area_query).all())
    if not areas:
        raise HTTPException(400, "No active search areas for this project — define one first")

    try:
        get_adapter(payload.provider)
    except ProviderError as exc:
        raise HTTPException(400, str(exc))

    run = DiscoveryRun(
        project_id=project.id,
        provider=payload.provider,
        area_ids=[a.id for a in areas],
        params={"tile_radius_m": payload.tile_radius_m, "max_calls": payload.max_calls},
        status=RunStatus.PENDING,
        created_by=user.id,
    )
    db.add(run)
    db.flush()
    write_audit(db, user, "DISCOVERY_SWEEP_STARTED", "discovery_run", run.id, {
        "provider": payload.provider.value,
        "areas": [a.id for a in areas],
        "tile_radius_m": payload.tile_radius_m,
    })
    db.commit()
    db.refresh(run)

    background.add_task(_execute_sweep, run.id, payload.tile_radius_m, payload.max_calls)
    return run


def _execute_sweep(run_id: int, tile_radius_m: float, max_calls: int | None) -> None:
    """Background worker. Owns its own session; failures land on the run row."""
    db = SessionLocal()
    try:
        run = db.get(DiscoveryRun, run_id)
        if not run:
            return
        areas = list(db.scalars(select(SearchArea).where(SearchArea.id.in_(run.area_ids))).all())
        try:
            adapter = get_adapter(run.provider)
        except ProviderError as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            run.finished_at = utcnow()
            db.commit()
            return
        run_sweep(db, run, adapter, areas, tile_radius_m=tile_radius_m, max_calls=max_calls)
        db.commit()
    finally:
        db.close()


@router.get("/sweeps", response_model=list[DiscoveryRunOut])
def list_runs(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES, UserRole.QA_REVIEWER, UserRole.AUDITOR, UserRole.CUSTOMER_VIEWER))],
):
    return list(db.scalars(select(DiscoveryRun).where(DiscoveryRun.project_id == project_id).order_by(DiscoveryRun.id.desc())).all())


@router.get("/sweeps/{run_id}", response_model=DiscoveryRunOut)
def get_run(
    run_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES, UserRole.QA_REVIEWER, UserRole.AUDITOR, UserRole.CUSTOMER_VIEWER))],
):
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Discovery run not found")
    return run


@router.post("/match/{project_id}")
def run_matching(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES))],
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    result = run_bulk_match(db, project)
    write_audit(db, user, "COMPARISON_MATCH_RUN", "project", project_id, result)
    db.commit()
    return result


@router.post("/probe")
def run_probes(
    payload: ProbeRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES))],
):
    """Prove or disprove uniqueness for records the bulk match could not resolve.

    Each place is looked up in the *opposite* provider. This is what licenses the
    'unique to Grab' / 'unique to Google' claim in the report.
    """
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    providers = [payload.provider] if payload.provider else [Provider.GRAB, Provider.GOOGLE]
    adapters = {}
    for provider in providers:
        opposite = Provider.GOOGLE if provider == Provider.GRAB else Provider.GRAB
        try:
            adapters[provider] = get_adapter(opposite)
        except ProviderError as exc:
            raise HTTPException(400, f"Cannot probe {provider.value} records: {exc}")

    summary = {"probed": 0, "unique_verified": 0, "matched": 0, "possible": 0, "unresolved": 0}
    remaining = payload.limit
    for provider in providers:
        opposite = Provider.GOOGLE if provider == Provider.GRAB else Provider.GRAB
        for place in unprobed_places(db, project.id, provider):
            if remaining <= 0:
                break
            if place.lat is None or place.lng is None:
                continue
            probe = probe_place(db, project, place, adapters[provider], opposite)
            summary["probed"] += 1
            key = {
                "UNIQUE_VERIFIED": "unique_verified",
                "MATCHED": "matched",
                "POSSIBLE_MATCH": "possible",
                "UNRESOLVED": "unresolved",
            }[probe.verdict.value]
            summary[key] += 1
            remaining -= 1

    write_audit(db, user, "UNIQUENESS_PROBE_RUN", "project", project.id, summary)
    db.commit()
    return summary
