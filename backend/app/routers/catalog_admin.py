"""Catalog editing: services, resources, instructors (constructor with many-to-many)."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from ..db import get_db
from ..deps import get_current_user, require_manager, require_admin
from ..models import (
    Service, Instructor, Resource, Zone, InstructorSpecialization,
    InstructorServicePrice, InstructorResource, ResourceService, Specialization, User,
    Booking,
)
from ..enums import BookingStatus, AuditAction, ServiceCategory, Season
from .. import audit


# Канонический прайс МГГК Крылатское 2026 (из docx):
PRICE_FROM_DOCX = [
    # (category, name, sku, price_rub, duration, group_size, season, is_trial, is_kids)
    ("range", "Range: 1 корзина (40 мячей)", "range-basket-40", 1500, 60, None, "summer", False, False),
    ("driving_range", "Драйвинг-рэндж, 1 час (будни)", "driving-weekday-1h", 3000, 60, None, "summer", False, False),
    ("driving_range", "Драйвинг-рэндж, 1 час (выходные)", "driving-weekend-1h", 3000, 60, None, "summer", False, False),
    ("academic_holes", "Лунки 19, 20", "academic-holes-19-20", 2000, 60, None, "summer", False, False),
    # Пробные
    ("lesson_trial", "Пробная персональная тренировка (1 гость)", "trial-lesson-1", 7000, 60, 1, "all_year", True, False),
    ("lesson_trial", "Пробная групповая тренировка (2 гостя)", "trial-lesson-2", 10000, 60, 2, "all_year", True, False),
    ("lesson_trial", "Пробная групповая тренировка (3 гостя)", "trial-lesson-3", 12000, 60, 3, "all_year", True, False),
    ("lesson_trial", "Пробная групповая тренировка (4 гостя)", "trial-lesson-4", 14000, 60, 4, "all_year", True, False),
    # Взрослые
    ("lesson", "Персональная тренировка (1 гость)", "lesson-1", 10000, 60, 1, "all_year", False, False),
    ("lesson", "Групповая тренировка (2 гостя)", "lesson-2", 14000, 60, 2, "all_year", False, False),
    ("lesson", "Групповая тренировка (3 гостя)", "lesson-3", 18000, 60, 3, "all_year", False, False),
    ("lesson", "Групповая тренировка (4 гостя)", "lesson-4", 21000, 60, 4, "all_year", False, False),
    # Детские
    ("lesson_kids", "Персональная тренировка (1 ребёнок до 16)", "kids-lesson-1", 7000, 60, 1, "all_year", False, True),
    ("lesson_kids", "Групповая тренировка (2 ребёнка до 16)", "kids-lesson-2", 10000, 60, 2, "all_year", False, True),
    ("lesson_kids", "Групповая тренировка (3 ребёнка до 16)", "kids-lesson-3", 12000, 60, 3, "all_year", False, True),
    ("lesson_kids", "Групповая тренировка (4 ребёнка до 16)", "kids-lesson-4", 14000, 60, 4, "all_year", False, True),
]

router = APIRouter(prefix="/catalog-admin", tags=["catalog-admin"])


# ── Services ─────────────────────────────────────────────────────────
class ServiceIn(BaseModel):
    category: str
    name: str
    sku: str
    duration_min: int = 60
    base_price_kopecks: int
    group_size: Optional[int] = None
    season: str = "all_year"
    is_trial: bool = False
    is_kids: bool = False
    requires_instructor: bool = False
    description: str = ""
    active: bool = True


class ServicePricePreview(BaseModel):
    current_price_kopecks: int
    new_price_kopecks: int
    future_bookings_count: int
    total_impact_kopecks: int


@router.post("/services", response_model=dict, status_code=201)
def create_service(
    payload: ServiceIn,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    if payload.category not in {c.value for c in ServiceCategory}:
        raise HTTPException(400, "Invalid category")
    if db.execute(select(Service).where(Service.sku == payload.sku)).scalar_one_or_none():
        raise HTTPException(409, "SKU already exists")
    svc = Service(**payload.model_dump())
    db.add(svc)
    db.flush()
    audit.log(db, user, AuditAction.CREATE.value, "service", svc.id,
              summary=f"Создана услуга: {svc.name}")
    db.commit()
    return {"id": svc.id}


@router.put("/services/{sid}")
def update_service(
    sid: int,
    payload: ServiceIn,
    apply_to_bookings: bool = False,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    svc = db.get(Service, sid)
    if not svc:
        raise HTTPException(404, "Not found")
    old_price = svc.base_price_kopecks
    for k, v in payload.model_dump().items():
        setattr(svc, k, v)
    audit.log(db, user, AuditAction.UPDATE.value, "service", sid,
              summary=f"Изменена услуга {svc.name}")

    # Cascade: apply new price to future unpaid bookings
    if apply_to_bookings and payload.base_price_kopecks != old_price:
        future = db.execute(
            select(Booking).where(
                Booking.service_id == sid,
                Booking.status.in_([BookingStatus.CONFIRMED.value, BookingStatus.HELD.value]),
                Booking.payment_status != "paid",
            )
        ).scalars().all()
        for b in future:
            b.price_kopecks = payload.base_price_kopecks * max(1, b.guests)
            b.total_kopecks = max(0, b.price_kopecks - b.discount_kopecks)
        if future:
            audit.log(db, user, AuditAction.UPDATE.value, "service", sid,
                      summary=f"Каскад цены на {len(future)} броней")

    db.commit()
    return {"ok": True}


@router.post("/services/{sid}/toggle")
def toggle_service(
    sid: int,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    svc = db.get(Service, sid)
    if not svc:
        raise HTTPException(404, "Not found")
    svc.active = not svc.active
    audit.log(db, user, AuditAction.UPDATE.value, "service", sid,
              summary=f'{"Активирована" if svc.active else "Выключена"} услуга: {svc.name}')
    db.commit()
    return {"active": svc.active}


@router.get("/services/{sid}/cascade-preview", response_model=ServicePricePreview)
def cascade_preview(
    sid: int,
    new_price_kopecks: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = db.get(Service, sid)
    if not svc:
        raise HTTPException(404, "Not found")
    future = db.execute(
        select(Booking).where(
            Booking.service_id == sid,
            Booking.status.in_([BookingStatus.CONFIRMED.value, BookingStatus.HELD.value]),
            Booking.payment_status != "paid",
        )
    ).scalars().all()
    delta_total = sum(
        (new_price_kopecks - svc.base_price_kopecks) * max(1, b.guests)
        for b in future
    )
    return ServicePricePreview(
        current_price_kopecks=svc.base_price_kopecks,
        new_price_kopecks=new_price_kopecks,
        future_bookings_count=len(future),
        total_impact_kopecks=delta_total,
    )


# ── Instructor constructor ───────────────────────────────────────────
class InstructorIn(BaseModel):
    name: str
    phone: str = ""
    email: str = ""
    bio: str = ""
    color: str = "#C9A961"
    specialization: str = ""
    working_hours: dict = Field(default_factory=dict)
    active: bool = True


class InstructorFull(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str
    email: str
    bio: str
    color: str
    specialization: str
    working_hours: dict
    active: bool
    specialization_ids: List[int] = []
    resource_ids: List[int] = []
    service_prices: dict[int, int] = Field(default_factory=dict)


@router.get("/instructors/{iid}", response_model=InstructorFull)
def get_instructor(iid: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    i = db.get(Instructor, iid)
    if not i:
        raise HTTPException(404, "Not found")
    spec_ids = [sp.id for sp in i.specializations]
    resource_ids = [r.resource_id for r in db.execute(
        select(InstructorResource).where(InstructorResource.instructor_id == iid)
    ).scalars()]
    price_rows = db.execute(
        select(InstructorServicePrice).where(InstructorServicePrice.instructor_id == iid)
    ).scalars()
    prices = {p.service_id: p.price_kopecks for p in price_rows}
    return InstructorFull(
        id=i.id, name=i.name, phone=i.phone, email=i.email, bio=i.bio,
        color=i.color, specialization=i.specialization,
        working_hours=i.working_hours or {}, active=i.active,
        specialization_ids=spec_ids, resource_ids=resource_ids,
        service_prices=prices,
    )


@router.post("/instructors", response_model=dict, status_code=201)
def create_instructor(
    payload: InstructorIn,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    i = Instructor(**payload.model_dump())
    db.add(i)
    db.flush()
    audit.log(db, user, AuditAction.CREATE.value, "instructor", i.id,
              summary=f"Добавлен тренер: {i.name}")
    db.commit()
    return {"id": i.id}


class InstructorAssignments(BaseModel):
    specialization_ids: List[int] = []
    resource_ids: List[int] = []


@router.put("/instructors/{iid}")
def update_instructor(
    iid: int,
    payload: InstructorIn,
    assignments: Optional[InstructorAssignments] = None,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    i = db.get(Instructor, iid)
    if not i:
        raise HTTPException(404, "Not found")
    for k, v in payload.model_dump().items():
        setattr(i, k, v)

    if assignments is not None:
        db.execute(delete(InstructorSpecialization).where(
            InstructorSpecialization.instructor_id == iid
        ))
        for sp_id in assignments.specialization_ids:
            db.add(InstructorSpecialization(instructor_id=iid, specialization_id=sp_id))
        db.execute(delete(InstructorResource).where(InstructorResource.instructor_id == iid))
        for r_id in assignments.resource_ids:
            db.add(InstructorResource(instructor_id=iid, resource_id=r_id))

    audit.log(db, user, AuditAction.UPDATE.value, "instructor", iid,
              summary=f"Обновлён тренер: {i.name}")
    db.commit()
    return {"ok": True}


@router.delete("/instructors/{iid}", status_code=204)
def delete_instructor(
    iid: int,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    i = db.get(Instructor, iid)
    if not i:
        raise HTTPException(404, "Not found")
    name = i.name
    # Detach the trainer from any historic bookings so FK doesn't block the delete.
    db.execute(
        Booking.__table__.update()
        .where(Booking.instructor_id == iid)
        .values(instructor_id=None)
    )
    # Clear all link tables explicitly (cascade already covers these but be explicit).
    db.execute(delete(InstructorSpecialization).where(InstructorSpecialization.instructor_id == iid))
    db.execute(delete(InstructorResource).where(InstructorResource.instructor_id == iid))
    db.execute(delete(InstructorServicePrice).where(InstructorServicePrice.instructor_id == iid))
    db.delete(i)
    audit.log(db, user, AuditAction.DELETE.value, "instructor", iid,
              summary=f"Удалён тренер: {name}")
    db.commit()


class InstructorPricePatch(BaseModel):
    service_id: int
    price_kopecks: int  # 0 = remove override


@router.post("/instructors/{iid}/service-price")
def set_instructor_price(
    iid: int,
    payload: InstructorPricePatch,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    if not db.get(Instructor, iid):
        raise HTTPException(404, "Instructor not found")
    existing = db.execute(
        select(InstructorServicePrice).where(
            InstructorServicePrice.instructor_id == iid,
            InstructorServicePrice.service_id == payload.service_id,
        )
    ).scalar_one_or_none()
    if payload.price_kopecks == 0:
        if existing:
            db.delete(existing)
    else:
        if existing:
            existing.price_kopecks = payload.price_kopecks
        else:
            db.add(InstructorServicePrice(
                instructor_id=iid,
                service_id=payload.service_id,
                price_kopecks=payload.price_kopecks,
            ))
    db.commit()
    return {"ok": True}


# ── Resource editor ──────────────────────────────────────────────────
class ResourceIn(BaseModel):
    name: str
    code: str
    capacity: int = 1
    season: str = "all_year"
    color: str = ""
    active: bool = True
    service_ids: List[int] = []


@router.put("/resources/{rid}")
def update_resource(
    rid: int,
    payload: ResourceIn,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    r = db.get(Resource, rid)
    if not r:
        raise HTTPException(404, "Not found")
    r.name = payload.name
    r.code = payload.code
    r.capacity = payload.capacity
    r.season = payload.season
    r.color = payload.color
    r.active = payload.active

    db.execute(delete(ResourceService).where(ResourceService.resource_id == rid))
    for sid in payload.service_ids:
        db.add(ResourceService(resource_id=rid, service_id=sid))

    audit.log(db, user, AuditAction.UPDATE.value, "resource", rid,
              summary=f"Обновлён ресурс: {r.name}")
    db.commit()
    return {"ok": True}


class ResourceFull(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    zone_id: int
    name: str
    code: str
    capacity: int
    season: str
    color: str
    active: bool
    service_ids: List[int] = []


@router.get("/resources/{rid}", response_model=ResourceFull)
def get_resource(rid: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.get(Resource, rid)
    if not r:
        raise HTTPException(404, "Not found")
    service_ids = [row.service_id for row in db.execute(
        select(ResourceService).where(ResourceService.resource_id == rid)
    ).scalars()]
    return ResourceFull(
        id=r.id, zone_id=r.zone_id, name=r.name, code=r.code, capacity=r.capacity,
        season=r.season, color=r.color, active=r.active, service_ids=service_ids,
    )


@router.post("/reset-services-from-price")
def reset_services_from_price(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Стирает все услуги и пересоздаёт ровно из прайс-листа МГГК 2026."""
    # Remove services not referenced by active bookings — safe zero-downtime.
    all_services = list(db.execute(select(Service)).scalars())
    for svc in all_services:
        # Detach via hard delete only if no bookings reference; else just deactivate.
        linked = db.execute(
            select(Booking).where(Booking.service_id == svc.id).limit(1)
        ).scalar_one_or_none()
        if linked:
            svc.active = False
        else:
            db.delete(svc)
    db.flush()

    requires_instructor = {"lesson", "lesson_trial", "lesson_kids"}
    created = 0
    for (cat, name, sku, price_rub, dur, grp, season, trial, kids) in PRICE_FROM_DOCX:
        existing = db.execute(select(Service).where(Service.sku == sku)).scalar_one_or_none()
        if existing:
            existing.category = cat
            existing.name = name
            existing.base_price_kopecks = price_rub * 100
            existing.duration_min = dur
            existing.group_size = grp
            existing.season = season
            existing.is_trial = trial
            existing.is_kids = kids
            existing.requires_instructor = cat in requires_instructor
            existing.active = True
        else:
            db.add(Service(
                category=cat, name=name, sku=sku,
                base_price_kopecks=price_rub * 100,
                duration_min=dur, group_size=grp, season=season,
                is_trial=trial, is_kids=kids,
                requires_instructor=cat in requires_instructor,
                active=True,
            ))
            created += 1

    audit.log(db, user, AuditAction.UPDATE.value, "services", None,
              summary=f"Сброс каталога услуг по прайсу: создано {created}, всего {len(PRICE_FROM_DOCX)}")
    db.commit()
    return {"total": len(PRICE_FROM_DOCX), "created": created}
