from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..auth import require_roles
from ..database import get_db
from ..models import AuditLog, User, UserRole
from ..schemas import AuditOut

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.AUDITOR, UserRole.QA_REVIEWER))],
    limit: int = Query(default=100, ge=1, le=500),
):
    return db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
