from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.usuario import Usuario


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(db: Session = Depends(get_db)) -> Usuario:
    """Stub de autenticacion.

    La autenticacion sigue siendo decorativa (AGENTS.md §7). La emision real de
    JWT corresponde a Feature 006 (`core/security.py` + `endpoints/auth.py`).
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Autenticacion no implementada. Prevista en Feature 006.",
    )
