"""Первичный сид для МГГК · Крылатское."""
from __future__ import annotations
from .db import get_session
from .domain import (
    User, UserRole,
    Facility, Zone, ResourceType, Resource, AvailabilityRule,
    Instructor, Service, ServiceCategory, Season, ResourceKind,
    MembershipPlan, AppSetting,
)
from .domain.models import (
    Specialization, InstructorSpecialization, InstructorServicePrice,
    InstructorResource, ResourceService,
)
from .services.auth import hash_password


def seed_if_empty():
    s = get_session()
    if s.query(User).count() > 0:
        return  # уже засеяно

    # ─── admin по умолчанию ──
    s.add(User(
        username='admin',
        password_hash=hash_password('admin'),
        name='Администратор',
        role=UserRole.ADMIN.value,
    ))
    s.add(User(
        username='manager',
        password_hash=hash_password('manager'),
        name='Менеджер Клуба',
        role=UserRole.MANAGER.value,
    ))
    s.add(User(
        username='cashier',
        password_hash=hash_password('cashier'),
        name='Анна Касса',
        role=UserRole.ACCOUNTING.value,
    ))

    # ─── Facility ──
    facility = Facility(
        name='МГГК · Крылатское',
        code='krylatskoe',
        address='Москва, Крылатское',
        timezone='Europe/Moscow',
    )
    s.add(facility)
    s.flush()

    # ─── ResourceTypes ──
    rt_range = ResourceType(kind=ResourceKind.RANGE_BAY.value, name='Range bay',
                            code='range_bay', default_duration_min=60, icon='target',
                            color='#C9A961')
    rt_driving = ResourceType(kind=ResourceKind.RANGE_BAY.value, name='Драйвинг-рэндж',
                              code='driving_bay', default_duration_min=60, icon='zap',
                              color='#2E9A6A')
    rt_hole = ResourceType(kind=ResourceKind.HOLE.value, name='Лунка',
                           code='hole', default_duration_min=60, icon='flag',
                           color='#155E3F')
    rt_sim = ResourceType(kind=ResourceKind.SIMULATOR_BAY.value, name='Симулятор',
                          code='simulator', default_duration_min=60, icon='monitor',
                          color='#3A6EA5')
    rt_lesson = ResourceType(kind=ResourceKind.LESSON_SLOT.value, name='Урок',
                             code='lesson', default_duration_min=60, icon='user-cog',
                             color='#8B5A96')
    rt_billiard = ResourceType(kind=ResourceKind.BILLIARD_TABLE.value, name='Бильярд',
                               code='billiard', default_duration_min=60, icon='circle-dot',
                               color='#7A5A10')
    for rt in (rt_range, rt_driving, rt_hole, rt_sim, rt_lesson, rt_billiard):
        s.add(rt)
    s.flush()

    # ─── Zones ──
    z_range = Zone(facility_id=facility.id, name='Range', code='range', sort_order=1)
    z_driving = Zone(facility_id=facility.id, name='Драйвинг-рэндж', code='driving', sort_order=2)
    z_academic = Zone(facility_id=facility.id, name='Академические лунки', code='academic', sort_order=3)
    z_sim = Zone(facility_id=facility.id, name='Симуляторы', code='simulators', sort_order=4)
    z_lessons = Zone(facility_id=facility.id, name='Уроки', code='lessons', sort_order=5)
    z_billiard = Zone(facility_id=facility.id, name='Бильярд', code='billiard', sort_order=6)
    for z in (z_range, z_driving, z_academic, z_sim, z_lessons, z_billiard):
        s.add(z)
    s.flush()

    # ─── Resources ──
    resources = []
    # Range — 8 байев (корзины), только лето
    for i in range(1, 9):
        resources.append(Resource(
            zone_id=z_range.id, resource_type_id=rt_range.id,
            name=f'Range bay {i}', code=f'R{i}', sort_order=i,
            season=Season.SUMMER.value,
        ))
    # Драйвинг-рэндж — 4 позиции
    for i in range(1, 5):
        resources.append(Resource(
            zone_id=z_driving.id, resource_type_id=rt_driving.id,
            name=f'Драйвинг {i}', code=f'D{i}', sort_order=i,
            season=Season.SUMMER.value,
        ))
    # Академические лунки
    for n in (19, 20):
        resources.append(Resource(
            zone_id=z_academic.id, resource_type_id=rt_hole.id,
            name=f'Лунка {n}', code=f'H{n}', sort_order=n,
            season=Season.SUMMER.value,
        ))
    # Симуляторы — 4 шт
    for i in range(1, 5):
        resources.append(Resource(
            zone_id=z_sim.id, resource_type_id=rt_sim.id,
            name=f'SkyTrak {i}', code=f'S{i}', sort_order=i,
            season=Season.ALL_YEAR.value,
        ))
    # Тренировочные слоты (всегда доступны)
    for i in range(1, 4):
        resources.append(Resource(
            zone_id=z_lessons.id, resource_type_id=rt_lesson.id,
            name=f'Trainer slot {i}', code=f'T{i}', sort_order=i,
            season=Season.ALL_YEAR.value,
        ))
    # Бильярд — 2 стола
    for i in range(1, 3):
        resources.append(Resource(
            zone_id=z_billiard.id, resource_type_id=rt_billiard.id,
            name=f'Стол {i}', code=f'B{i}', sort_order=i,
            season=Season.ALL_YEAR.value,
        ))
    for r in resources:
        s.add(r)
    s.flush()

    # ─── Availability rules: все ресурсы 08:00–22:00 круглый год ──
    for r in resources:
        s.add(AvailabilityRule(
            resource_id=r.id, weekday=None,
            open_time='08:00', close_time='22:00',
            season=Season.ALL_YEAR.value,
        ))

    # ─── Справочник специализаций тренеров ──
    spec_pga = Specialization(
        name='PGA Pro', code='pga',
        description='Сертифицированный PGA тренер, уроки продвинутого уровня',
        applicable_categories=['lesson', 'lesson_trial'], sort_order=1,
    )
    spec_driving = Specialization(
        name='Уроки на поле', code='on_course',
        description='Практика на тренировочном поле и лунках 19–20',
        applicable_categories=['lesson', 'lesson_trial', 'driving_range'], sort_order=2,
    )
    spec_sim = Specialization(
        name='Симулятор', code='simulator',
        description='Работа на гольф-симуляторе (SkyTrak, Trackman)',
        applicable_categories=['simulator', 'lesson'], sort_order=3,
    )
    spec_kids = Specialization(
        name='Детский тренер', code='kids',
        description='Занятия с детьми до 16 лет',
        applicable_categories=['lesson_kids'], sort_order=4,
    )
    spec_short = Specialization(
        name='Short game', code='short_game',
        description='Чиппинг, питчинг, бункер, паттинг',
        applicable_categories=['lesson', 'academic_holes'], sort_order=5,
    )
    spec_fit = Specialization(
        name='Fitting', code='fitting',
        description='Подбор клюшек, club fitting',
        applicable_categories=['lesson'], sort_order=6,
    )
    for sp in (spec_pga, spec_driving, spec_sim, spec_kids, spec_short, spec_fit):
        s.add(sp)
    s.flush()

    # ─── Instructors ──
    i_matr = Instructor(
        name='Матросов Алексей Викторович',
        specialization='PGA, уроки на поле',
        phone='+7 (985) 111-22-33',
        bio='PGA Pro, 15 лет опыта. Специализация — уроки на поле и работа с продвинутыми игроками.',
        color='#2E9A6A',
        working_hours={
            'mon': ['09:00', '20:00'], 'tue': ['09:00', '20:00'], 'wed': ['09:00', '20:00'],
            'thu': ['09:00', '20:00'], 'fri': ['09:00', '20:00'],
            'sat': ['10:00', '18:00'], 'sun': ['10:00', '18:00'],
        },
    )
    i_ivan = Instructor(
        name='Иванов Иван Иванович',
        specialization='Симулятор, детские группы',
        phone='+7 (985) 222-33-44',
        bio='Тренер по симулятору, 8 лет опыта. Детские и групповые занятия.',
        color='#3A6EA5',
    )
    i_petr = Instructor(
        name='Петрова Елена Сергеевна',
        specialization='Start-to-golf, Step By Step',
        phone='+7 (985) 333-44-55',
        bio='Методика Start-to-golf для начинающих. Программа Step By Step.',
        color='#C9A961',
    )
    for i in (i_matr, i_ivan, i_petr):
        s.add(i)
    s.flush()

    # ─── Привязка специализаций к тренерам ──
    instructor_specs = [
        (i_matr, [spec_pga, spec_driving, spec_short, spec_fit]),
        (i_ivan, [spec_sim, spec_kids]),
        (i_petr, [spec_driving, spec_kids]),
    ]
    for instr, specs in instructor_specs:
        for sp in specs:
            s.add(InstructorSpecialization(instructor_id=instr.id, specialization_id=sp.id))

    # ─── Services (прайс 2026 · Крылатское) ──
    services = [
        # Range
        ('Range: 1 корзина (40 мячей)', ServiceCategory.RANGE, 'range-basket-40',
         1_500_00, 60, None, Season.SUMMER, False, False),

        # Драйвинг-рэндж
        ('Драйвинг-рэндж, 1 час (будни)', ServiceCategory.DRIVING_RANGE, 'driving-weekday-1h',
         3_000_00, 60, None, Season.SUMMER, False, False),
        ('Драйвинг-рэндж, 1 час (выходные)', ServiceCategory.DRIVING_RANGE, 'driving-weekend-1h',
         3_000_00, 60, None, Season.SUMMER, False, False),

        # Академические лунки
        ('Лунки 19, 20', ServiceCategory.ACADEMIC_HOLES, 'academic-holes-19-20',
         2_000_00, 60, None, Season.SUMMER, False, False),

        # Пробные тренировки
        ('Пробная тренировка (1 гость)', ServiceCategory.LESSON_TRIAL, 'trial-lesson-1',
         7_000_00, 60, 1, Season.ALL_YEAR, True, False),
        ('Пробная тренировка (2 гостя)', ServiceCategory.LESSON_TRIAL, 'trial-lesson-2',
         10_000_00, 60, 2, Season.ALL_YEAR, True, False),
        ('Пробная тренировка (3 гостя)', ServiceCategory.LESSON_TRIAL, 'trial-lesson-3',
         12_000_00, 60, 3, Season.ALL_YEAR, True, False),
        ('Пробная тренировка (4 гостя)', ServiceCategory.LESSON_TRIAL, 'trial-lesson-4',
         14_000_00, 60, 4, Season.ALL_YEAR, True, False),

        # Тренировки взрослые
        ('Тренировка (1 гость)', ServiceCategory.LESSON, 'lesson-1',
         10_000_00, 60, 1, Season.ALL_YEAR, False, False),
        ('Тренировка (2 гостя)', ServiceCategory.LESSON, 'lesson-2',
         14_000_00, 60, 2, Season.ALL_YEAR, False, False),
        ('Тренировка (3 гостя)', ServiceCategory.LESSON, 'lesson-3',
         18_000_00, 60, 3, Season.ALL_YEAR, False, False),
        ('Тренировка (4 гостя)', ServiceCategory.LESSON, 'lesson-4',
         21_000_00, 60, 4, Season.ALL_YEAR, False, False),

        # Детские
        ('Детская тренировка (1 ребёнок)', ServiceCategory.LESSON_KIDS, 'kids-lesson-1',
         7_000_00, 60, 1, Season.ALL_YEAR, False, True),
        ('Детская тренировка (2 ребёнка)', ServiceCategory.LESSON_KIDS, 'kids-lesson-2',
         10_000_00, 60, 2, Season.ALL_YEAR, False, True),
        ('Детская тренировка (3 ребёнка)', ServiceCategory.LESSON_KIDS, 'kids-lesson-3',
         12_000_00, 60, 3, Season.ALL_YEAR, False, True),
        ('Детская тренировка (4 ребёнка)', ServiceCategory.LESSON_KIDS, 'kids-lesson-4',
         14_000_00, 60, 4, Season.ALL_YEAR, False, True),

        # Симулятор
        ('Игра на гольф-симуляторе', ServiceCategory.SIMULATOR, 'simulator-play',
         4_000_00, 60, None, Season.ALL_YEAR, False, False),
        ('Урок на гольф-симуляторе', ServiceCategory.SIMULATOR, 'simulator-lesson',
         8_000_00, 60, 1, Season.ALL_YEAR, False, False),

        # Бильярд
        ('Бильярд, 1 час', ServiceCategory.BILLIARD, 'billiard-1h',
         1_500_00, 60, None, Season.ALL_YEAR, False, False),

        # Экскурсия
        ('Экскурсия по клубу', ServiceCategory.EXCURSION, 'club-tour',
         0, 60, None, Season.ALL_YEAR, False, False),
    ]

    requires_instructor_cats = {
        ServiceCategory.LESSON.value,
        ServiceCategory.LESSON_TRIAL.value,
        ServiceCategory.LESSON_KIDS.value,
    }

    for name, cat, sku, price, dur, grp, season, trial, kids in services:
        s.add(Service(
            category=cat.value, name=name, sku=sku,
            base_price_kopecks=price, duration_min=dur, group_size=grp,
            season=season.value, is_trial=trial, is_kids=kids,
            requires_instructor=(cat.value in requires_instructor_cats),
        ))

    # ─── Membership plans ──
    s.add(MembershipPlan(
        name='Standard', tier=1, price_kopecks=0,
        duration_days=365, discount_percent=0,
        description='Стандартный гость без привилегий',
    ))
    s.add(MembershipPlan(
        name='Silver', tier=2, price_kopecks=50_000_00,
        duration_days=365, discount_percent=10, priority_booking_days=7,
        description='Скидка 10%, приоритетная бронь за неделю',
    ))
    s.add(MembershipPlan(
        name='Gold', tier=3, price_kopecks=150_000_00,
        duration_days=365, discount_percent=20, priority_booking_days=14,
        description='Скидка 20%, приоритетная бронь за 2 недели',
    ))
    s.add(MembershipPlan(
        name='Platinum', tier=4, price_kopecks=400_000_00,
        duration_days=365, discount_percent=30, priority_booking_days=30,
        description='Скидка 30%, приоритетная бронь за месяц, персональный тренер',
    ))

    # ─── App settings ──
    s.add(AppSetting(key='facility_id', value=str(facility.id)))
    s.add(AppSetting(key='season_mode', value='auto'))

    s.commit()
