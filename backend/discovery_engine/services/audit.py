from sqlalchemy.orm import Session
from ..models import AuditLog, User


def write_audit(db: Session, user: User | None, action: str, entity_type: str, entity_id: str | int | None, details: dict | None = None) -> None:
    db.add(AuditLog(
        actor_id=user.id if user else None,
        actor_email=user.email if user else "system",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {},
    ))
