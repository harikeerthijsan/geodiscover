from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..database import get_db
from ..models import PoiCandidate, Project, User
from ..schemas import DashboardKpi
from ..services.kpi import calculate_kpis

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/{project_id}", response_model=DashboardKpi)
def dashboard(project_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    candidates = db.scalars(select(PoiCandidate).where(PoiCandidate.project_id == project_id)).all()
    return calculate_kpis(candidates)
