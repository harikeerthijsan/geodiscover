"""Single-action city discovery: pick a city, run everything, download the result."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..config import get_settings
from ..data.indonesia import provinces, resolve
from ..database import SessionLocal, get_db
from ..models import DiscoveryJob, ExportRecord, JobStage, Project, RunStatus, User, UserRole, utcnow
from ..schemas import CityJobOut, CityJobRequest
from ..services.audit import write_audit
from ..services.comparison_report import build_comparison_geojson, build_comparison_workbook
from ..services.jobs import available_providers, create_job, estimate_job, execute_job

router = APIRouter(prefix="/jobs", tags=["City Discovery"])

WRITE_ROLES = (UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST)
READ_ROLES = WRITE_ROLES + (UserRole.QA_REVIEWER, UserRole.AUDITOR, UserRole.CUSTOMER_VIEWER)


@router.get("/regions")
def list_regions(user: Annotated[User, Depends(require_roles(*READ_ROLES))]):
    """Indonesian provinces and cities available for selection."""
    settings = get_settings()
    return {
        "provinces": provinces(),
        "providers_configured": [p.value for p in available_providers(settings)],
        "note": (
            "Radii approximate the built-up area, not the administrative boundary. "
            "CORE covers the central commercial district; FULL covers the urban extent "
            "and costs substantially more."
        ),
    }


@router.post("/estimate")
def estimate(
    payload: CityJobRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    """Cost estimate for a city. Spends nothing."""
    city = resolve(payload.city_code)
    if not city:
        raise HTTPException(404, f"Unknown city code: {payload.city_code}")
    return estimate_job(city, payload.coverage, payload.tile_radius_m)


@router.post("", response_model=CityJobOut, status_code=202)
def start_job(
    payload: CityJobRequest,
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*WRITE_ROLES))],
):
    """Start a city discovery job.

    Requires ``confirm: true``. The estimate endpoint is deliberately a separate,
    free call — a run spends real money against live provider APIs, so it should
    never be startable by accident.
    """
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    city = resolve(payload.city_code)
    if not city:
        raise HTTPException(404, f"Unknown city code: {payload.city_code}")

    settings = get_settings()
    providers = available_providers(settings)
    if not providers:
        raise HTTPException(400, "No provider credentials configured — set GOOGLE_MAPS_API_KEY and/or AWS_LOCATION_API_KEY")
    if not payload.confirm:
        raise HTTPException(400, "Set confirm=true to start a run. Call /jobs/estimate first to see the cost.")

    job = create_job(db, project, city, payload.coverage, payload.tile_radius_m, user.id)
    if payload.max_probe_calls:
        job.max_probe_calls = payload.max_probe_calls
    write_audit(db, user, "CITY_JOB_STARTED", "discovery_job", job.id, {
        "city": city.name,
        "province": city.province,
        "coverage": job.coverage,
        "radius_m": job.radius_m,
        "est_cost_usd": job.est_cost_usd,
        "providers": [p.value for p in providers],
    })
    db.commit()
    db.refresh(job)

    background.add_task(_execute, job.id)
    return job


def _execute(job_id: int) -> None:
    """Background worker. Owns its own session; failures land on the job row."""
    db = SessionLocal()
    try:
        job = db.get(DiscoveryJob, job_id)
        if not job:
            return
        try:
            execute_job(db, job)
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            job.status = RunStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"[:2000]
            job.finished_at = utcnow()
        db.commit()
    finally:
        db.close()


@router.get("", response_model=list[CityJobOut])
def list_jobs(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    return list(db.scalars(select(DiscoveryJob).where(DiscoveryJob.project_id == project_id).order_by(DiscoveryJob.id.desc())).all())


@router.get("/{job_id}", response_model=CityJobOut)
def get_job(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    job = db.get(DiscoveryJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/{job_id}/export.xlsx")
def download_job(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    """Download the unique-records workbook for one city."""
    job = db.get(DiscoveryJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.stage != JobStage.FINISHED and job.status == RunStatus.RUNNING:
        raise HTTPException(409, f"Job is still running (stage: {job.stage.value}) — poll /jobs/{job_id} until it finishes")

    project = db.get(Project, job.project_id)
    content, file_name, kpis = build_comparison_workbook(db, project, job=job)
    db.add(ExportRecord(
        project_id=project.id,
        file_name=file_name,
        record_count=kpis["GU_grab_only_verified"] + kpis["KU_google_only_verified"],
        validation_summary={k: v for k, v in kpis.items() if not isinstance(v, list)},
        created_by=user.id,
    ))
    write_audit(db, user, "CITY_JOB_EXPORTED", "discovery_job", job.id, {
        "file_name": file_name,
        "city": job.city_name,
        "grab_only": kpis["GU_grab_only_verified"],
        "google_only": kpis["KU_google_only_verified"],
    })
    db.commit()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/{job_id}/export.geojson")
def download_job_geojson(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*READ_ROLES))],
):
    job = db.get(DiscoveryJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return build_comparison_geojson(db, db.get(Project, job.project_id), job_id=job.id)
