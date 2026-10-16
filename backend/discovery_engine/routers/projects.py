from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..auth import get_current_user, require_roles
from ..database import get_db
from ..models import Project, User, UserRole
from ..schemas import ProjectCreate, ProjectOut
from ..services.audit import write_audit

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    return db.scalars(select(Project).order_by(Project.created_at.desc())).all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER))],
):
    project = Project(**payload.model_dump(), created_by=user.id)
    db.add(project)
    db.flush()
    write_audit(db, user, "PROJECT_CREATED", "project", project.id, {"name": project.name})
    db.commit()
    db.refresh(project)
    return project
