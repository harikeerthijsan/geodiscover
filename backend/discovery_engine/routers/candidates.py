from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..database import get_db
from ..models import GoogleCheck, GoogleStatus, PoiCandidate, Project, User, UserRole
from ..schemas import CandidateOut, CandidateUpdate, GoogleReviewRequest
from ..services.audit import write_audit
from ..services.eligibility import recalculate_candidate
from ..services.normalization import normalize_text

router = APIRouter(prefix="/candidates", tags=["POI Candidates"])


@router.get("")
def list_candidates(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    search: str | None = None,
    city: str | None = None,
    source: str | None = None,
    google_status: GoogleStatus | None = None,
    usable_only: bool = False,
):
    filters = [PoiCandidate.project_id == project_id]
    if search:
        filters.append(func.lower(PoiCandidate.business_name).contains(search.lower()))
    if city:
        filters.append(PoiCandidate.city == city)
    if source:
        filters.append(PoiCandidate.source_name == source)
    if google_status:
        filters.append(PoiCandidate.google_status == google_status)
    if usable_only:
        filters.append(PoiCandidate.usability_eligible.is_(True))
    total = db.scalar(select(func.count()).select_from(PoiCandidate).where(*filters)) or 0
    rows = db.scalars(
        select(PoiCandidate).where(*filters).order_by(PoiCandidate.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [CandidateOut.model_validate(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{candidate_id}", response_model=CandidateOut)
def get_candidate(candidate_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    return candidate


@router.patch("/{candidate_id}", response_model=CandidateOut)
def update_candidate(
    candidate_id: int,
    payload: CandidateUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST, UserRole.GOOGLE_VALIDATOR, UserRole.QA_REVIEWER))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    project = db.get(Project, candidate.project_id)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(candidate, key, value)
    if "business_name" in changes:
        candidate.normalized_name = normalize_text(candidate.business_name)
    candidate.updated_by = user.id
    recalculate_candidate(candidate, project)
    write_audit(db, user, "CANDIDATE_UPDATED", "poi_candidate", candidate.id, {"fields": list(changes)})
    db.commit()
    db.refresh(candidate)
    return candidate


@router.post("/{candidate_id}/google-review", response_model=CandidateOut)
def google_review(
    candidate_id: int,
    payload: GoogleReviewRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.GOOGLE_VALIDATOR, UserRole.QA_REVIEWER))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    if payload.decision == GoogleStatus.GOOGLE_ABSENT_VERIFIED:
        if not payload.completed:
            raise HTTPException(422, "Verified Google absence requires a completed review")
        if not payload.queries:
            raise HTTPException(422, "Verified Google absence requires structured query evidence")
        if not payload.evidence_reference:
            raise HTTPException(422, "Verified Google absence requires an evidence reference")
    check = GoogleCheck(
        poi_candidate_id=candidate.id,
        decision=payload.decision,
        queries=payload.queries,
        candidate_place_ids=payload.candidate_place_ids,
        reviewer=user.email,
        reason=payload.reason,
        evidence_reference=payload.evidence_reference,
        completed=payload.completed,
    )
    db.add(check)
    candidate.google_status = payload.decision
    candidate.google_review_completed = payload.completed
    candidate.google_reviewer = user.email
    candidate.reviewer_identity = user.email
    if payload.evidence_reference:
        candidate.evidence_reference = payload.evidence_reference
    recalculate_candidate(candidate, candidate.project)
    write_audit(db, user, "GOOGLE_REVIEW_COMPLETED", "poi_candidate", candidate.id, {
        "decision": payload.decision.value,
        "completed": payload.completed,
        "reason": payload.reason,
    })
    db.commit()
    db.refresh(candidate)
    return candidate
