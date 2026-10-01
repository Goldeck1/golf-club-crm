"""
Единая доменная модель GolfAdmin.
Структура:
  Users                          — сотрудники с ролями
  Facility → Zone → Resource     — физическая инфраструктура
  Customers / Members            — гости и участники клуба
  Catalog (Service/AddOn/...)    — что можно купить/забронировать
  Bookings + Items + Group       — бронирования и их состав
  Commerce (Order/Payment)       — деньги
  Promo (Coupon/Voucher/Promo)   — скидки и пакеты
  AuditLog, Notification, Setting
"""

from __future__ import annotations
from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import (
    String, Integer, BigInteger, Boolean, DateTime, Date, Text, Float,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from flask_login import UserMixin

from ..db import Base
from .enums import (
    UserRole, BookingStatus, PaymentStatus, ResourceKind,
    ServiceCategory, Season, NotificationState, AuditAction,
)


# ─── Mixins ─────────────────────────────────────────────────────────

def _now():
    return datetime.utcnow()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


# ─── Users ──────────────────────────────────────────────────────────

class User(Base, TimestampMixin, UserMixin):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default='')
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=UserRole.STAFF.value)
    telegram_chat_id: Mapped[str] = mapped_column(String(64), default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    @property
    def is_admin(self): return self.role == UserRole.ADMIN.value
    @property
    def is_manager(self): return self.role in (UserRole.ADMIN.value, UserRole.MANAGER.value)
    @property
    def is_accounting(self): return self.role in (UserRole.ADMIN.value, UserRole.ACCOUNTING.value)

    def __repr__(self): return f'<User {self.username} ({self.role})>'


# ─── Facilities / Resources ─────────────────────────────────────────

class Facility(Base, TimestampMixin):
    __tablename__ = 'facilities'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    address: Mapped[str] = mapped_column(String(255), default='')
    timezone: Mapped[str] = mapped_column(String(64), default='Europe/Moscow')
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    zones: Mapped[List['Zone']] = relationship(back_populates='facility', cascade='all, delete-orphan')


class Zone(Base, TimestampMixin):
    __tablename__ = 'zones'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey('facilities.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    facility: Mapped[Facility] = relationship(back_populates='zones')
    resources: Mapped[List['Resource']] = relationship(back_populates='zone', cascade='all, delete-orphan')

    __table_args__ = (UniqueConstraint('facility_id', 'code'),)


class ResourceType(Base, TimestampMixin):
    __tablename__ = 'resource_types'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)   # ResourceKind
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    default_duration_min: Mapped[int] = mapped_column(Integer, default=60)
    default_capacity: Mapped[int] = mapped_column(Integer, default=1)
    icon: Mapped[str] = mapped_column(String(64), default='map-pin')
    color: Mapped[str] = mapped_column(String(16), default='#155E3F')
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    resources: Mapped[List['Resource']] = relationship(back_populates='resource_type')


class Resource(Base, TimestampMixin):
    """Конкретный bookable ресурс: лунка 19, range bay #4, симулятор SkyTrak #1, комната массажа."""
    __tablename__ = 'resources'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey('zones.id', ondelete='CASCADE'), nullable=False)
    resource_type_id: Mapped[int] = mapped_column(ForeignKey('resource_types.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    season: Mapped[str] = mapped_column(String(16), default=Season.ALL_YEAR.value)
    color: Mapped[str] = mapped_column(String(16), default='')      # override resource_type.color
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    zone: Mapped[Zone] = relationship(back_populates='resources')
    resource_type: Mapped[ResourceType] = relationship(back_populates='resources')
    availability_rules: Mapped[List['AvailabilityRule']] = relationship(
        back_populates='resource', cascade='all, delete-orphan'
    )
    blackouts: Mapped[List['Blackout']] = relationship(
        back_populates='resource', cascade='all, delete-orphan'
    )

    __table_args__ = (UniqueConstraint('zone_id', 'code'),)

    @property
    def display_color(self) -> str:
        return self.color or (self.resource_type.color if self.resource_type else '#155E3F')


class AvailabilityRule(Base, TimestampMixin):
    """Правила рабочих часов ресурса. Если правил нет — берутся default из config."""
    __tablename__ = 'availability_rules'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey('resources.id', ondelete='CASCADE'), nullable=False)
    # weekday: 0=Mon...6=Sun, NULL = любой
    weekday: Mapped[Optional[int]] = mapped_column(Integer)
    open_time: Mapped[str] = mapped_column(String(5), nullable=False)      # "08:00"
    close_time: Mapped[str] = mapped_column(String(5), nullable=False)     # "22:00"
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    season: Mapped[str] = mapped_column(String(16), default=Season.ALL_YEAR.value)

    resource: Mapped[Resource] = relationship(back_populates='availability_rules')


class Blackout(Base, TimestampMixin):
    """Период, когда ресурс недоступен (ремонт, погода, закрытие на турнир)."""
    __tablename__ = 'blackouts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[Optional[int]] = mapped_column(ForeignKey('resources.id', ondelete='CASCADE'))
    facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey('facilities.id', ondelete='CASCADE'))
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default='')
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'))

    resource: Mapped[Optional[Resource]] = relationship(back_populates='blackouts')


# ─── Customers / Members ────────────────────────────────────────────

class Customer(Base, TimestampMixin):
    """Единая сущность клиента. member status = через Membership."""
    __tablename__ = 'customers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default='', index=True)
    email: Mapped[str] = mapped_column(String(128), default='', index=True)
    car_brand: Mapped[str] = mapped_column(String(64), default='')
    car_number: Mapped[str] = mapped_column(String(32), default='')
    birthdate: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default='')
    # marketing
    consent_marketing: Mapped[bool] = mapped_column(Boolean, default=False)
    tg_chat_id: Mapped[str] = mapped_column(String(64), default='')

    account: Mapped[Optional['Account']] = relationship(back_populates='customer', uselist=False, cascade='all, delete-orphan')
    memberships: Mapped[List['Membership']] = relationship(back_populates='customer', cascade='all, delete-orphan')
    bookings: Mapped[List['Booking']] = relationship(back_populates='customer')


class Account(Base, TimestampMixin):
    """House account — баланс клиента, предоплаты, vouchers."""
    __tablename__ = 'accounts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id', ondelete='CASCADE'), unique=True, nullable=False)
    balance_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    credit_limit_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)

    customer: Mapped[Customer] = relationship(back_populates='account')


class MembershipPlan(Base, TimestampMixin):
    __tablename__ = 'membership_plans'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)       # "Gold", "Family", "Corporate"
    tier: Mapped[int] = mapped_column(Integer, default=1)               # 1..5
    price_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=365)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    priority_booking_days: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base, TimestampMixin):
    __tablename__ = 'memberships'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey('membership_plans.id'), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    customer: Mapped[Customer] = relationship(back_populates='memberships')
    plan: Mapped[MembershipPlan] = relationship()


# ─── Catalog ────────────────────────────────────────────────────────

class Specialization(Base, TimestampMixin):
    """Справочник специализаций тренеров: Driving coach / PGA / Short game / Симулятор / Fitting / Юниоры."""
    __tablename__ = 'specializations'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default='')
    # К каким категориям услуг применима (помогает авто-подбирать услуги при настройке тренера)
    applicable_categories: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    instructors: Mapped[List['Instructor']] = relationship(
        secondary='instructor_specializations', back_populates='specializations'
    )


class InstructorSpecialization(Base):
    """M2M: тренер ↔ специализация."""
    __tablename__ = 'instructor_specializations'
    instructor_id: Mapped[int] = mapped_column(ForeignKey('instructors.id', ondelete='CASCADE'), primary_key=True)
    specialization_id: Mapped[int] = mapped_column(ForeignKey('specializations.id', ondelete='CASCADE'), primary_key=True)


class Instructor(Base, TimestampMixin):
    __tablename__ = 'instructors'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Наследие: plain-текст специализация (будет выведена из справочника через M2M specializations)
    specialization: Mapped[str] = mapped_column(String(255), default='')
    color: Mapped[str] = mapped_column(String(16), default='#C9A961')
    bio: Mapped[str] = mapped_column(Text, default='')
    avatar_url: Mapped[str] = mapped_column(String(255), default='')
    phone: Mapped[str] = mapped_column(String(32), default='')
    email: Mapped[str] = mapped_column(String(128), default='')
    # Рабочие часы: {"mon": ["09:00","18:00"], "tue": [...], ...} ; пусто = 08:00-22:00
    working_hours: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    specializations: Mapped[List['Specialization']] = relationship(
        secondary='instructor_specializations', back_populates='instructors'
    )
    service_prices: Mapped[List['InstructorServicePrice']] = relationship(
        back_populates='instructor', cascade='all, delete-orphan'
    )
    resource_assignments: Mapped[List['InstructorResource']] = relationship(
        back_populates='instructor', cascade='all, delete-orphan'
    )


class InstructorServicePrice(Base, TimestampMixin):
    """Персональный прайс тренера на конкретную услугу (override base_price)."""
    __tablename__ = 'instructor_service_prices'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instructor_id: Mapped[int] = mapped_column(ForeignKey('instructors.id', ondelete='CASCADE'), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    instructor: Mapped['Instructor'] = relationship(back_populates='service_prices')
    service: Mapped['Service'] = relationship()

    __table_args__ = (UniqueConstraint('instructor_id', 'service_id'),)


class InstructorResource(Base):
    """M2M: на каких ресурсах тренер может проводить занятия."""
    __tablename__ = 'instructor_resources'
    instructor_id: Mapped[int] = mapped_column(ForeignKey('instructors.id', ondelete='CASCADE'), primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey('resources.id', ondelete='CASCADE'), primary_key=True)

    instructor: Mapped['Instructor'] = relationship(back_populates='resource_assignments')
    resource: Mapped['Resource'] = relationship()


class ResourceService(Base):
    """M2M: какие услуги доступны на ресурсе (например, на SkyTrak — только симуляторные)."""
    __tablename__ = 'resource_services'
    resource_id: Mapped[int] = mapped_column(ForeignKey('resources.id', ondelete='CASCADE'), primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey('services.id', ondelete='CASCADE'), primary_key=True)


class Service(Base, TimestampMixin):
    __tablename__ = 'services'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, default=60)
    base_price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_size: Mapped[Optional[int]] = mapped_column(Integer)
    season: Mapped[str] = mapped_column(String(16), default=Season.ALL_YEAR.value)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    is_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_instructor: Mapped[bool] = mapped_column(Boolean, default=False)
    applicable_resource_kinds: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServicePricing(Base, TimestampMixin):
    """Правило ценообразования поверх base_price: день недели, время, сезон, mem-tier."""
    __tablename__ = 'service_pricing'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    weekdays: Mapped[list] = mapped_column(JSON, default=list)      # [0..6]
    time_from: Mapped[Optional[str]] = mapped_column(String(5))
    time_to: Mapped[Optional[str]] = mapped_column(String(5))
    season: Mapped[str] = mapped_column(String(16), default=Season.ALL_YEAR.value)
    member_tier_min: Mapped[int] = mapped_column(Integer, default=0)
    price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AddOn(Base, TimestampMixin):
    __tablename__ = 'addons'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Package(Base, TimestampMixin):
    """Набор услуг со скидкой (N уроков, подписка)."""
    __tablename__ = 'packages'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    includes: Mapped[dict] = mapped_column(JSON, default=dict)   # {"service_sku": count}
    valid_days: Mapped[int] = mapped_column(Integer, default=365)
    description: Mapped[str] = mapped_column(Text, default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ─── Promotions / Vouchers ──────────────────────────────────────────

class Coupon(Base, TimestampMixin):
    __tablename__ = 'coupons'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default='percent')   # percent | fixed
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    max_uses: Mapped[int] = mapped_column(Integer, default=0)
    max_uses_per_user: Mapped[int] = mapped_column(Integer, default=0)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    stackable: Mapped[bool] = mapped_column(Boolean, default=False)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Voucher(Base, TimestampMixin):
    """Подарочный сертификат, заранее оплаченный, расходуется на брони."""
    __tablename__ = 'vouchers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    issued_to_customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey('customers.id'))
    valid_until: Mapped[Optional[date]] = mapped_column(Date)
    redeemed: Mapped[bool] = mapped_column(Boolean, default=False)


class Promotion(Base, TimestampMixin):
    __tablename__ = 'promotions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default='discount')  # discount|package|free_addon
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    stackable: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ─── Bookings ───────────────────────────────────────────────────────

class BookingGroup(Base, TimestampMixin):
    """Для сложных броней: один чек, несколько ресурсов/услуг."""
    __tablename__ = 'booking_groups'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey('customers.id'))
    title: Mapped[str] = mapped_column(String(255), default='')
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'))

    items: Mapped[List['Booking']] = relationship(back_populates='group')


class Booking(Base, TimestampMixin):
    __tablename__ = 'bookings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey('booking_groups.id', ondelete='SET NULL'))

    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey('customers.id'))
    resource_id: Mapped[Optional[int]] = mapped_column(ForeignKey('resources.id'))
    service_id: Mapped[Optional[int]] = mapped_column(ForeignKey('services.id'))
    instructor_id: Mapped[Optional[int]] = mapped_column(ForeignKey('instructors.id'))

    guests: Mapped[int] = mapped_column(Integer, default=1)
    with_guest: Mapped[bool] = mapped_column(Boolean, default=False)

    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(16), default=BookingStatus.CONFIRMED.value, index=True)
    payment_status: Mapped[str] = mapped_column(String(24), default=PaymentStatus.PENDING.value, index=True)

    # Денежные значения в копейках (чтобы не было float-артефактов)
    price_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    discount_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    total_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)

    comment: Mapped[str] = mapped_column(Text, default='')
    internal_notes: Mapped[str] = mapped_column(Text, default='')

    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cancel_reason: Mapped[str] = mapped_column(String(255), default='')
    no_show_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'))

    # relationships
    group: Mapped[Optional[BookingGroup]] = relationship(back_populates='items')
    customer: Mapped[Optional[Customer]] = relationship(back_populates='bookings')
    resource: Mapped[Optional[Resource]] = relationship()
    service: Mapped[Optional[Service]] = relationship()
    instructor: Mapped[Optional[Instructor]] = relationship()
    items: Mapped[List['BookingItem']] = relationship(back_populates='booking', cascade='all, delete-orphan')

    __table_args__ = (
        Index('ix_bookings_resource_time', 'resource_id', 'starts_at', 'ends_at'),
        CheckConstraint('ends_at > starts_at', name='booking_time_valid'),
    )

    # Convenience
    @property
    def duration_min(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    @property
    def is_active(self) -> bool:
        return self.status in (
            BookingStatus.HELD.value,
            BookingStatus.CONFIRMED.value,
            BookingStatus.CHECKED_IN.value,
        )

    @property
    def is_realized(self) -> bool:
        """Попадает в realized revenue? — только completed + paid."""
        return (
            self.status == BookingStatus.COMPLETED.value
            and self.payment_status in (PaymentStatus.PAID.value, PaymentStatus.PARTIALLY_REFUNDED.value)
        )


class BookingItem(Base, TimestampMixin):
    """Строки брони — основная услуга, add-on, промо-скидка."""
    __tablename__ = 'booking_items'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey('bookings.id', ondelete='CASCADE'), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default='service')   # service|addon|discount|fee
    service_id: Mapped[Optional[int]] = mapped_column(ForeignKey('services.id'))
    addon_id: Mapped[Optional[int]] = mapped_column(ForeignKey('addons.id'))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    total_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)

    booking: Mapped[Booking] = relationship(back_populates='items')


class Waitlist(Base, TimestampMixin):
    __tablename__ = 'waitlists'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'), nullable=False)
    resource_id: Mapped[Optional[int]] = mapped_column(ForeignKey('resources.id'))
    service_id: Mapped[Optional[int]] = mapped_column(ForeignKey('services.id'))
    desired_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    desired_to: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    fulfilled: Mapped[bool] = mapped_column(Boolean, default=False)


class CheckIn(Base, TimestampMixin):
    __tablename__ = 'checkins'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey('bookings.id', ondelete='CASCADE'), nullable=False)
    by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'))
    at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    note: Mapped[str] = mapped_column(String(255), default='')


# ─── Commerce ───────────────────────────────────────────────────────

class Order(Base, TimestampMixin):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # O-2026-000123
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey('customers.id'))
    booking_id: Mapped[Optional[int]] = mapped_column(ForeignKey('bookings.id'))
    subtotal_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    discount_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    total_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str] = mapped_column(String(8), default='RUB')
    status: Mapped[str] = mapped_column(String(16), default='open')  # open|paid|refunded|void
    coupon_code: Mapped[str] = mapped_column(String(64), default='')
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'))

    items: Mapped[List['OrderItem']] = relationship(back_populates='order', cascade='all, delete-orphan')
    payments: Mapped[List['Payment']] = relationship(back_populates='order', cascade='all, delete-orphan')


class OrderItem(Base, TimestampMixin):
    __tablename__ = 'order_items'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default='service')
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)

    order: Mapped[Order] = relationship(back_populates='items')


class Payment(Base, TimestampMixin):
    __tablename__ = 'payments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default='manual')
    provider_ref: Mapped[str] = mapped_column(String(128), default='', index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), default='', index=True)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=PaymentStatus.PENDING.value)
    method: Mapped[str] = mapped_column(String(32), default='cash')   # cash|card|online|house
    captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    failure_reason: Mapped[str] = mapped_column(String(255), default='')
    received_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'))

    order: Mapped[Order] = relationship(back_populates='payments')
    refunds: Mapped[List['Refund']] = relationship(back_populates='payment', cascade='all, delete-orphan')


class Refund(Base, TimestampMixin):
    __tablename__ = 'refunds'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey('payments.id', ondelete='CASCADE'), nullable=False)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default='')
    provider_ref: Mapped[str] = mapped_column(String(128), default='')
    status: Mapped[str] = mapped_column(String(24), default='pending')
    refunded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'))

    payment: Mapped[Payment] = relationship(back_populates='refunds')


# ─── Audit / Notifications / Settings ───────────────────────────────

class AuditLog(Base):
    __tablename__ = 'audit_log'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False, index=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'))
    actor_username: Mapped[str] = mapped_column(String(64), default='')
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    summary: Mapped[str] = mapped_column(String(255), default='')
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default='')


class Notification(Base, TimestampMixin):
    __tablename__ = 'notifications'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), default='telegram')
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default=NotificationState.PENDING.value)
    related_entity: Mapped[str] = mapped_column(String(64), default='')
    related_id: Mapped[Optional[int]] = mapped_column(Integer)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error: Mapped[str] = mapped_column(String(255), default='')


class AppSetting(Base, TimestampMixin):
    __tablename__ = 'app_settings'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default='')
