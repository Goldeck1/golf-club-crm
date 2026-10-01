from datetime import datetime, date, timedelta, time
from collections import defaultdict
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import select, and_, or_

from ..db import get_session
from ..domain import (
    Booking, BookingStatus, Resource, Service, Customer, Instructor, Zone, ResourceType,
)
from ..services.scheduler import visible_resources, find_conflicts
from ..services import booking_service

bp = Blueprint('calendar', __name__)


# ─── Главная tee sheet страница ────────────────────────────────────

@bp.route('/calendar')
@login_required
def index():
    view = request.args.get('view', 'resource')   # resource | day | week | heatmap
    day_str = request.args.get('date', date.today().isoformat())
    try:
        on = date.fromisoformat(day_str)
    except ValueError:
        on = date.today()

    resources = visible_resources()
    # группировка по зоне
    by_zone = defaultdict(list)
    for r in resources:
        by_zone[r.zone.name].append(r)

    return render_template('calendar/index.html',
                           view=view,
                           on=on,
                           prev_day=(on - timedelta(days=1)).isoformat(),
                           next_day=(on + timedelta(days=1)).isoformat(),
                           resources_by_zone=by_zone,
                           all_resources=resources)


# ─── FullCalendar events feed ──────────────────────────────────────

@bp.route('/api/calendar/events')
@login_required
def events():
    s = get_session()
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    start = datetime.fromisoformat(start_str.replace('Z', '').split('+')[0]) if start_str else datetime.now()
    end = datetime.fromisoformat(end_str.replace('Z', '').split('+')[0]) if end_str else start + timedelta(days=1)

    q = select(Booking).where(
        Booking.starts_at < end,
        Booking.ends_at > start,
        Booking.status != BookingStatus.CANCELLED.value,
    )
    bookings = s.execute(q).scalars().all()

    status_colors = {
        BookingStatus.DRAFT.value:      '#9DADA3',
        BookingStatus.HELD.value:       '#C9A961',
        BookingStatus.CONFIRMED.value:  '#155E3F',
        BookingStatus.CHECKED_IN.value: '#2E9A6A',
        BookingStatus.COMPLETED.value:  '#5D6F64',
        BookingStatus.NO_SHOW.value:    '#C13B3B',
    }

    out = []
    for b in bookings:
        title = b.customer.name if b.customer else 'Без клиента'
        if b.service:
            title += f' · {b.service.name}'
        out.append({
            'id': b.id,
            'resourceId': b.resource_id,
            'start': b.starts_at.isoformat(),
            'end': b.ends_at.isoformat(),
            'title': title,
            'backgroundColor': status_colors.get(b.status, '#155E3F'),
            'borderColor': status_colors.get(b.status, '#155E3F'),
            'textColor': '#fff',
            'extendedProps': {
                'status': b.status,
                'payment_status': b.payment_status,
                'price_kopecks': b.total_kopecks,
                'customer_name': b.customer.name if b.customer else None,
                'customer_phone': b.customer.phone if b.customer else None,
                'service_name': b.service.name if b.service else None,
                'instructor_name': b.instructor.name if b.instructor else None,
                'guests': b.guests,
            },
        })
    return jsonify(out)


@bp.route('/api/calendar/resources')
@login_required
def resources_feed():
    """Feed для FullCalendar resource timeline."""
    out = []
    for r in visible_resources():
        out.append({
            'id': r.id,
            'title': r.name,
            'group': r.zone.name,
            'eventColor': r.display_color,
        })
    return jsonify(out)


# ─── Drag-and-drop handlers (HTMX/AJAX) ────────────────────────────

@bp.route('/api/calendar/booking/<int:bid>/move', methods=['POST'])
@login_required
def move_booking(bid):
    s = get_session()
    booking = s.get(Booking, bid)
    if not booking:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    try:
        start = datetime.fromisoformat(request.json['start'].replace('Z', '').split('+')[0])
        end   = datetime.fromisoformat(request.json['end'].replace('Z', '').split('+')[0])
        resource_id = int(request.json.get('resource_id') or booking.resource_id)
    except (KeyError, ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'bad_input'}), 400

    try:
        booking_service.reschedule(booking, resource_id=resource_id, starts_at=start, ends_at=end)
    except booking_service.SchedulerConflict as e:
        return jsonify({'ok': False, 'error': 'conflict',
                        'message': str(e),
                        'conflicts': [c.id for c in e.conflicts]}), 409
    return jsonify({'ok': True})
