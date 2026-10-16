"""Coverage-comparison KPIs, record buckets, match review and reports."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..database import get_db
from ..models import (
    ExportRecord, MatchMethod, PoiMatch, Project, Provider, ProviderPlace,
    UniquenessProbe, UniquenessVerdict, User, UserRole, utcnow,
)
from ..schemas import (
    MatchReviewRequest, PlaceCounterpartOut, PlaceEvidenceOut, PoiMatchOut,
    ProviderPlaceDetail, ProviderPlaceOut, ProviderPlacePage,
)
from ..services.audit import write_audit
from ..services.comparison import bucket_records, calculate_comparison_kpis
from ..services.comparison_report import build_comparison_geojson, build_comparison_workbook
from ..services.normalization import normalize_text
from ..services.probe import apply_verdicts

router = APIRouter(prefix="/comparison", tags=["Comparison"])

READ_ROLES = (
    UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST,
    UserRole.QA_REVIEWER, UserRole.AUDITOR, UserRole.CUSTOMER_VIEWER,
)

BUCKETS = {
    "matched", "grab_only", "google_only",
    "grab_possible", "google_possible", "grab_unresolved", "google_unresolved",
}


@router.get("/{project_id}/kpis")
def comparison_kpis(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    return calculate_comparison_kpis(db, project_id)


@router.get("/{project_id}/records", response_model=list[ProviderPlaceOut])
def comparison_records(
    project_id: int,
    bucket: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    if bucket not in BUCKETS:
        raise HTTPException(400, f"bucket must be one of: {', '.join(sorted(BUCKETS))}")
    return bucket_records(db, project_id, bucket)


@router.get("/{project_id}/places", response_model=ProviderPlacePage)
def browse_places(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
    provider: Provider | None = None,
    verdict: UniquenessVerdict | None = None,
    city: str | None = None,
    q: str | None = None,
    job_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
):
    """Browse the real discovered places, filtered and paginated."""
    page = max(page, 1)
    page_size = max(1, min(page_size, 500))

    query = select(ProviderPlace).where(
        ProviderPlace.project_id == project_id, ProviderPlace.in_scope.is_(True)
    )
    if provider:
        query = query.where(ProviderPlace.provider == provider)
    if verdict:
        query = query.where(ProviderPlace.verdict == verdict)
    if city:
        query = query.where(ProviderPlace.city == city)
    if job_id:
        query = query.where(ProviderPlace.job_id == job_id)
    if q:
        needle = f"%{normalize_text(q)}%"
        query = query.where(ProviderPlace.normalized_name.like(needle))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(ProviderPlace.name).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ProviderPlacePage(
        items=list(rows), total=total, page=page, page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.get("/places/{place_id}", response_model=ProviderPlaceDetail)
def place_detail(
    place_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    """One record with the evidence behind its verdict and any paired counterpart."""
    place = db.get(ProviderPlace, place_id)
    if not place:
        raise HTTPException(404, "Place not found")

    evidence = db.scalars(
        select(UniquenessProbe)
        .where(UniquenessProbe.provider_place_id == place.id)
        .order_by(UniquenessProbe.probed_at.desc())
    ).first()

    if place.provider == Provider.GRAB:
        matches = db.scalars(select(PoiMatch).where(PoiMatch.grab_place_id == place.id)).all()
        others = {m.id: db.get(ProviderPlace, m.google_place_id) for m in matches}
    else:
        matches = db.scalars(select(PoiMatch).where(PoiMatch.google_place_id == place.id)).all()
        others = {m.id: db.get(ProviderPlace, m.grab_place_id) for m in matches}

    counterparts = [
        PlaceCounterpartOut(
            provider=others[m.id].provider, name=others[m.id].name, address=others[m.id].address,
            score=m.score, distance_m=m.distance_m, decision=m.decision, method=m.method,
            signals=m.signals or {},
        )
        for m in sorted(matches, key=lambda m: m.score, reverse=True)
        if others.get(m.id) is not None
    ]

    detail = ProviderPlaceDetail.model_validate(place, from_attributes=True)
    detail.evidence = PlaceEvidenceOut.model_validate(evidence, from_attributes=True) if evidence else None
    detail.counterparts = counterparts
    return detail


@router.get("/{project_id}/cities")
def list_cities(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    rows = db.execute(
        select(ProviderPlace.city, func.count())
        .where(ProviderPlace.project_id == project_id, ProviderPlace.in_scope.is_(True))
        .group_by(ProviderPlace.city)
        .order_by(func.count().desc())
    ).all()
    return [{"city": r[0] or "Unknown", "count": r[1]} for r in rows]


@router.get("/{project_id}/matches", response_model=list[PoiMatchOut])
def list_matches(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
    decision: str | None = None,
):
    query = select(PoiMatch).where(PoiMatch.project_id == project_id)
    if decision:
        query = query.where(PoiMatch.decision == decision)
    return list(db.scalars(query.order_by(PoiMatch.score.desc())).all())


@router.post("/matches/{match_id}/review", response_model=PoiMatchOut)
def review_match(
    match_id: int,
    payload: MatchReviewRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.QA_REVIEWER))],
):
    """Human adjudication of a pair. A manual decision is never overwritten by a re-run."""
    match = db.get(PoiMatch, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    match.decision = payload.decision
    match.method = MatchMethod.MANUAL
    match.reviewer = user.email
    match.review_reason = payload.reason
    match.reviewed_at = utcnow()
    db.flush()
    apply_verdicts(db, match.project_id)
    write_audit(db, user, "MATCH_REVIEWED", "poi_match", match.id, {
        "decision": payload.decision.value,
        "reason": payload.reason,
        "score": match.score,
    })
    db.commit()
    db.refresh(match)
    return match


@router.get("/{project_id}/report.xlsx")
def comparison_report_xlsx(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    content, file_name, kpis = build_comparison_workbook(db, project)
    db.add(ExportRecord(
        project_id=project_id,
        file_name=file_name,
        record_count=kpis["GU_grab_only_verified"] + kpis["KU_google_only_verified"] + kpis["M_matched"],
        validation_summary={k: v for k, v in kpis.items() if not isinstance(v, list)},
        created_by=user.id,
    ))
    write_audit(db, user, "COMPARISON_REPORT_EXPORTED", "project", project_id, {
        "file_name": file_name,
        "grab_only": kpis["GU_grab_only_verified"],
        "google_only": kpis["KU_google_only_verified"],
        "matched": kpis["M_matched"],
        "invariants_pass": kpis["invariant_grab_partition"]
        and kpis["invariant_google_partition"]
        and kpis["invariant_unique_has_probe_evidence"],
    })
    db.commit()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/{project_id}/report.geojson")
def comparison_report_geojson(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return build_comparison_geojson(db, project)
