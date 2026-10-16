"""Three-map area comparison: draw a circle, sweep HERE + Google + Grab, compare."""
from __future__ import annotations

import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..config import get_settings
from ..database import SessionLocal, get_db
from ..models import (
    AreaCluster,
    AreaSweep,
    PresenceBucket,
    Project,
    Provider,
    ProviderPlace,
    RunStatus,
    User,
    UserRole,
)
from ..services.area_sweep import (
    ALL_PROVIDERS,
    provider_configured,
    DEFAULT_RADIUS_M,
    DEFAULT_TILE_RADIUS_M,
    category_options,
    estimate_area_sweep,
    execute_area_sweep,
)
from ..services.audit import write_audit
from ..services.excel_export import build_workbook, workbook_filename
from ..services.taxonomy import CATEGORY_LABELS, UnifiedCategory

router = APIRouter(prefix="/area", tags=["Area Comparison"])

WRITE_ROLES = (UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST)

#: Marker colours, shared with the interface legend so both stay in step.
BUCKET_STYLE: dict[str, dict[str, str]] = {
    PresenceBucket.ALL_THREE.value: {"label": "In all three maps", "color": "#2a6c9e"},
    PresenceBucket.HERE_GOOGLE.value: {"label": "HERE + Google only", "color": "#5b8c5a"},
    PresenceBucket.HERE_GRAB.value: {"label": "HERE + Grab only", "color": "#b97816"},
    PresenceBucket.GOOGLE_GRAB.value: {"label": "Google + Grab only", "color": "#8a6bbf"},
    PresenceBucket.HERE_ONLY.value: {"label": "HERE only", "color": "#13835d"},
    PresenceBucket.GOOGLE_ONLY.value: {"label": "Google only", "color": "#c4453c"},
    PresenceBucket.GRAB_ONLY.value: {"label": "Grab only", "color": "#0f7d8c"},
}


class AreaEstimateRequest(BaseModel):
    center_lat: float = Field(..., ge=-90, le=90)
    center_lng: float = Field(..., ge=-180, le=180)
    radius_m: float = Field(DEFAULT_RADIUS_M, gt=0, le=20000)
    tile_radius_m: float = Field(DEFAULT_TILE_RADIUS_M, ge=100, le=5000)
    categories: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)


class AreaSweepRequest(AreaEstimateRequest):
    project_id: int
    label: str = ""


@router.get("/options")
def options(user: Annotated[User, Depends(get_current_user)]):
    """Everything the interface needs to render the setup panel."""
    settings = get_settings()
    return {
        "categories": category_options(),
        "providers": [
            {
                "value": Provider.HERE.value,
                "label": "HERE",
                "configured": settings.here_enabled,
                "note": "HERE /browse, one call per category root per tile."
                        if settings.here_enabled else
                        "Not configured. Set HERE_API_KEY in backend/.env — create a key "
                        "at platform.here.com under Access Manager > Apps > Credentials.",
            },
            {
                "value": Provider.GOOGLE.value,
                "label": "Google Maps",
                "configured": settings.google_enabled,
                "note": "Google searchNearby, one call per category group per tile."
                        if settings.google_enabled else
                        "Not configured. Set GOOGLE_MAPS_API_KEY in backend/.env.",
            },
            {
                "value": Provider.GRAB.value,
                "label": "Grab Maps",
                "configured": settings.grab_enabled,
                "note": "Keyword-derived coverage: Grab has no radius search, so a Grab "
                        "gap is weaker evidence than a Google or HERE gap."
                        if settings.grab_enabled else
                        "Not configured. Set AWS_LOCATION_API_KEY, or AWS_ACCESS_KEY_ID "
                        "and AWS_SECRET_ACCESS_KEY, in backend/.env.",
            },
        ],
        "here_map_key": settings.here_api_key or None,
        "defaults": {"radius_m": DEFAULT_RADIUS_M, "tile_radius_m": DEFAULT_TILE_RADIUS_M},
        "buckets": [{"value": k, **v} for k, v in BUCKET_STYLE.items()],
    }


@router.post("/estimate")
def estimate(payload: AreaEstimateRequest, user: Annotated[User, Depends(get_current_user)]):
    """Cost and call estimate. Nothing is spent by calling this."""
    return estimate_area_sweep(
        payload.center_lat, payload.center_lng, payload.radius_m, payload.tile_radius_m,
        payload.categories or None, payload.providers or None,
    )


def _run_in_background(sweep_id: int) -> None:
    """Own session: the request's session is closed by the time this runs."""
    db = SessionLocal()
    try:
        sweep = db.get(AreaSweep, sweep_id)
        if sweep is None:
            return
        try:
            execute_area_sweep(db, sweep)
        except Exception as exc:  # noqa: BLE001 - the sweep row is the error report
            sweep.status = RunStatus.FAILED
            sweep.error = str(exc)[:2000]
            sweep.stage = "FAILED"
        db.commit()
    finally:
        db.close()


@router.post("/sweeps", status_code=201)
def create_sweep(
    payload: AreaSweepRequest,
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES))],
):
    """Start a three-map comparison over one circle. Runs in the background."""
    if not db.get(Project, payload.project_id):
        raise HTTPException(404, "Project not found")

    # An explicitly empty list is a mistake, never "sweep everything". Defaulting it to
    # all three would bill a full run to someone who deselected every provider.
    if payload.providers is not None and len(payload.providers) == 0:
        raise HTTPException(422, "Select at least one provider.")

    providers = payload.providers or [p.value for p in ALL_PROVIDERS]

    # One provider is allowed and useful — it answers "what does this map have here?".
    # It is an inventory, not a comparison, and the result is labelled that way: with
    # one source the presence buckets carry no meaning, because a place absent from the
    # others was never asked about. The distinction is enforced in the response, not by
    # refusing the run.
    unconfigured = []
    for value in providers:
        try:
            provider = Provider(value)
        except ValueError:
            raise HTTPException(422, f"Unknown provider: {value}")
        if not provider_configured(provider):
            unconfigured.append(value)
    # Refused rather than skipped: a comparison silently missing a leg would report
    # every place in the other maps as unique to them, which is a false finding.
    if unconfigured:
        raise HTTPException(422, (
            f"No API credentials for: {', '.join(unconfigured)}. Add them to backend/.env "
            "and restart, or deselect those providers. Nothing is ever substituted for "
            "missing provider data."
        ))

    sweep = AreaSweep(
        project_id=payload.project_id,
        label=payload.label or f"{payload.radius_m:.0f} m around {payload.center_lat:.5f}, {payload.center_lng:.5f}",
        center_lat=payload.center_lat,
        center_lng=payload.center_lng,
        radius_m=payload.radius_m,
        tile_radius_m=payload.tile_radius_m,
        categories=payload.categories,
        providers=providers,
        status=RunStatus.PENDING,
        stage="QUEUED",
        created_by=user.id,
    )
    sweep.est_cost_usd = estimate_area_sweep(
        payload.center_lat, payload.center_lng, payload.radius_m, payload.tile_radius_m,
        payload.categories or None, providers,
    )["cost_expected_total_usd"]
    db.add(sweep)
    db.flush()
    write_audit(db, user, "AREA_SWEEP_STARTED", "area_sweep", str(sweep.id), {
        "center": [payload.center_lat, payload.center_lng],
        "radius_m": payload.radius_m,
        "providers": providers,
        "est_cost_usd": sweep.est_cost_usd,
    })
    db.commit()
    background.add_task(_run_in_background, sweep.id)
    return _sweep_summary(sweep)


def _sweep_summary(sweep: AreaSweep) -> dict[str, Any]:
    return {
        "id": sweep.id,
        "project_id": sweep.project_id,
        "label": sweep.label,
        "center": {"lat": sweep.center_lat, "lng": sweep.center_lng},
        "radius_m": sweep.radius_m,
        "tile_radius_m": sweep.tile_radius_m,
        "categories": sweep.categories,
        "providers": sweep.providers,
        "status": sweep.status.value,
        "stage": sweep.stage,
        "provider_counts": sweep.provider_counts or {},
        "bucket_counts": sweep.bucket_counts or {},
        "category_matrix": sweep.category_matrix or {},
        "clusters_total": sweep.clusters_total,
        "api_calls": sweep.api_calls,
        "cost_breakdown": sweep.cost_breakdown or {},
        "est_cost_usd": sweep.est_cost_usd,
        "actual_cost_usd": sweep.actual_cost_usd,
        # One source is an inventory; two or more is a comparison. The interface uses
        # this to decide whether presence buckets may be shown as coverage findings.
        "is_comparison": len(set(sweep.providers or [])) > 1,
        "mode": "COMPARISON" if len(set(sweep.providers or [])) > 1 else "INVENTORY",
        "partial_providers": sweep.partial_providers or [],
        "error": sweep.error,
        "started_at": sweep.started_at.isoformat() if sweep.started_at else None,
        "finished_at": sweep.finished_at.isoformat() if sweep.finished_at else None,
    }


@router.get("/sweeps")
def list_sweeps(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    project_id: int | None = None,
    limit: int = Query(25, ge=1, le=200),
):
    query = select(AreaSweep).order_by(AreaSweep.id.desc()).limit(limit)
    if project_id:
        query = query.where(AreaSweep.project_id == project_id)
    return {"sweeps": [_sweep_summary(s) for s in db.scalars(query).all()]}


@router.get("/sweeps/{sweep_id}")
def get_sweep(
    sweep_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    sweep = db.get(AreaSweep, sweep_id)
    if not sweep:
        raise HTTPException(404, "Area sweep not found")
    summary = _sweep_summary(sweep)
    summary["bucket_legend"] = [{"value": k, **v} for k, v in BUCKET_STYLE.items()]
    summary["category_labels"] = {c.value: label for c, label in CATEGORY_LABELS.items()}
    return summary


def _cluster_row(cluster: AreaCluster, places: dict[int, ProviderPlace]) -> dict[str, Any]:
    def side(place_id: int | None) -> dict[str, Any] | None:
        place = places.get(place_id) if place_id else None
        if place is None:
            return None
        return {
            "id": place.id,
            "name": place.name,
            "address": place.address,
            "lat": place.lat,
            "lng": place.lng,
            "phone": place.phone_e164,
            "website": place.website,
            "categories": place.categories,
            "provider_place_id": place.provider_place_id,
        }

    return {
        "id": cluster.id,
        "bucket": cluster.bucket.value,
        "bucket_label": BUCKET_STYLE.get(cluster.bucket.value, {}).get("label", cluster.bucket.value),
        "category": cluster.unified_category,
        "category_label": CATEGORY_LABELS.get(
            UnifiedCategory(cluster.unified_category), cluster.unified_category
        ) if cluster.unified_category in UnifiedCategory._value2member_map_ else cluster.unified_category,
        "name": cluster.display_name,
        "address": cluster.address,
        "lat": cluster.lat,
        "lng": cluster.lng,
        "here": side(cluster.here_place_id),
        "google": side(cluster.google_place_id),
        "grab": side(cluster.grab_place_id),
        "match_evidence": cluster.match_evidence,
        "max_pair_distance_m": cluster.max_pair_distance_m,
    }


#: Which cluster column holds each provider's record.
_PROVIDER_COLUMN = {
    Provider.HERE.value: AreaCluster.here_place_id,
    Provider.GOOGLE.value: AreaCluster.google_place_id,
    Provider.GRAB.value: AreaCluster.grab_place_id,
}


def _load_clusters(
    db: Session, sweep_id: int, bucket: str | None, category: str | None,
    limit: int, offset: int, provider: str | None = None,
) -> tuple[list[AreaCluster], int, dict[int, ProviderPlace]]:
    query = select(AreaCluster).where(AreaCluster.sweep_id == sweep_id)
    if bucket:
        query = query.where(AreaCluster.bucket == PresenceBucket(bucket))
    if category:
        query = query.where(AreaCluster.unified_category == category)
    if provider:
        # "Everything this provider has here", regardless of who else has it.
        query = query.where(_PROVIDER_COLUMN[provider].is_not(None))
    total = len(db.scalars(query).all())
    rows = db.scalars(query.order_by(AreaCluster.id).offset(offset).limit(limit)).all()

    place_ids = {
        pid for row in rows
        for pid in (row.here_place_id, row.google_place_id, row.grab_place_id) if pid
    }
    places = {
        p.id: p for p in
        (db.scalars(select(ProviderPlace).where(ProviderPlace.id.in_(place_ids))).all() if place_ids else [])
    }
    return rows, total, places


@router.get("/sweeps/{sweep_id}/clusters")
def clusters(
    sweep_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    bucket: str | None = None,
    category: str | None = None,
    provider: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    if not db.get(AreaSweep, sweep_id):
        raise HTTPException(404, "Area sweep not found")
    if bucket and bucket not in PresenceBucket._value2member_map_:
        raise HTTPException(422, f"Unknown bucket: {bucket}")
    if provider and provider not in _PROVIDER_COLUMN:
        raise HTTPException(422, f"Unknown provider: {provider}")
    rows, total, places = _load_clusters(db, sweep_id, bucket, category, limit, offset, provider)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "clusters": [_cluster_row(row, places) for row in rows],
    }


@router.get("/sweeps/{sweep_id}/map.geojson")
def map_geojson(
    sweep_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    bucket: str | None = None,
    category: str | None = None,
    provider: str | None = None,
):
    """One point per resolved place, coloured by which maps hold it."""
    sweep = db.get(AreaSweep, sweep_id)
    if not sweep:
        raise HTTPException(404, "Area sweep not found")
    query = select(AreaCluster).where(
        AreaCluster.sweep_id == sweep_id,
        AreaCluster.lat.is_not(None),
        AreaCluster.lng.is_not(None),
    )
    if bucket:
        query = query.where(AreaCluster.bucket == PresenceBucket(bucket))
    if category:
        query = query.where(AreaCluster.unified_category == category)
    if provider:
        if provider not in _PROVIDER_COLUMN:
            raise HTTPException(422, f"Unknown provider: {provider}")
        query = query.where(_PROVIDER_COLUMN[provider].is_not(None))

    features = []
    for row in db.scalars(query).all():
        style = BUCKET_STYLE.get(row.bucket.value, {})
        features.append({
            "type": "Feature",
            "id": row.id,
            "geometry": {"type": "Point", "coordinates": [row.lng, row.lat]},
            "properties": {
                "cluster_id": row.id,
                "name": row.display_name,
                "address": row.address or "",
                "bucket": row.bucket.value,
                "bucket_label": style.get("label", row.bucket.value),
                "color": style.get("color", "#7d8c95"),
                "category": row.unified_category,
                "in_here": row.here_place_id is not None,
                "in_google": row.google_place_id is not None,
                "in_grab": row.grab_place_id is not None,
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "area": {
            "center": [sweep.center_lng, sweep.center_lat],
            "radius_m": sweep.radius_m,
        },
    }


@router.get("/sweeps/{sweep_id}/export.xlsx")
def export_xlsx(
    sweep_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Excel workbook for one sweep.

    An inventory gets a single POI sheet; a comparison gets one sheet per presence
    bucket, so "only in HERE", "only in Grab" and "in both" arrive as separate tabs
    in one file rather than as several downloads.
    """
    sweep = db.get(AreaSweep, sweep_id)
    if not sweep:
        raise HTTPException(404, "Area sweep not found")
    stream = build_workbook(db, sweep)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{workbook_filename(sweep)}"'},
    )


@router.get("/sweeps/{sweep_id}/export.csv")
def export_csv(
    sweep_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    bucket: str | None = None,
    category: str | None = None,
    provider: str | None = None,
):
    sweep = db.get(AreaSweep, sweep_id)
    if not sweep:
        raise HTTPException(404, "Area sweep not found")
    rows, _, places = _load_clusters(
        db, sweep_id, bucket, category, limit=100000, offset=0, provider=provider
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "cluster_id", "presence", "category", "name", "address", "latitude", "longitude",
        "in_here", "in_google", "in_grab",
        "here_name", "google_name", "grab_name",
        "phone", "website", "max_pair_distance_m", "evidence",
    ])
    for row in rows:
        data = _cluster_row(row, places)
        contact = data["google"] or data["here"] or {}
        writer.writerow([
            row.id, row.bucket.value, row.unified_category, row.display_name, row.address or "",
            row.lat if row.lat is not None else "", row.lng if row.lng is not None else "",
            "YES" if data["here"] else "NO",
            "YES" if data["google"] else "NO",
            "YES" if data["grab"] else "NO",
            (data["here"] or {}).get("name", ""),
            (data["google"] or {}).get("name", ""),
            (data["grab"] or {}).get("name", ""),
            contact.get("phone") or "", contact.get("website") or "",
            row.max_pair_distance_m if row.max_pair_distance_m is not None else "",
            "; ".join(f"{k}={v.get('score')}" for k, v in (row.match_evidence or {}).items()),
        ])
    buffer.seek(0)
    filename = f"area_comparison_{sweep_id}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
