from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..db import get_db
from ..deps import get_current_user
from ..models import Service, Instructor
from ..schemas import ServiceOut, InstructorOut

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/services", response_model=List[ServiceOut])
def list_services(
    category: Optional[str] = None,
    active_only: bool = True,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(Service).order_by(Service.category, Service.name)
    if active_only:
        q = q.where(Service.active == True)  # noqa: E712
    if category:
        q = q.where(Service.category == category)
    return list(db.execute(q).scalars())


@router.get("/instructors", response_model=List[InstructorOut])
def list_instructors(
    active_only: bool = True,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(Instructor).order_by(Instructor.name)
    if active_only:
        q = q.where(Instructor.active == True)  # noqa: E712
    return list(db.execute(q).scalars())
