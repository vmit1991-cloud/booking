import json
from datetime import time

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from .models import Booking, MeetingRoom


# ===========================
# WORKING HOURS CONFIG
# ===========================
WORK_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri
WORK_START = time(8, 0)     # 08:00
WORK_END = time(20, 0)      # 20:00 (end may be exactly 20:00)


# ===========================
# HELPERS
# ===========================
def _json_ok(extra=None):
    data = {"ok": True}
    if extra:
        data.update(extra)
    return JsonResponse(data)


def _json_error(message, *, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_body_json(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return None


def _booking_color(status: str) -> str:
    if status == Booking.Status.APPROVED:
        return "#2e7d32"
    if status == Booking.Status.PENDING:
        return "#6c757d"
    if status == Booking.Status.CANCELLED:
        return "#f57c00"
    return "#b71c1c"


def _ensure_aware(dt):
    if dt is None:
        return None
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt, timezone.get_current_timezone())


def _to_local(dt):
    """Convert datetime to local timezone from settings (Europe/Kyiv)."""
    dt = _ensure_aware(dt)
    if dt is None:
        return None
    return timezone.localtime(dt)


def _is_within_working_hours(start, end) -> bool:
    """
    Booking must be:
      - same day
      - Mon-Fri
      - within 08:00..20:00 (end may be exactly 20:00)
    All checks are in LOCAL timezone.
    """
    if not start or not end:
        return False

    start_local = _to_local(start)
    end_local = _to_local(end)

    if not start_local or not end_local:
        return False

    if end_local <= start_local:
        return False

    # Must be same local date
    if start_local.date() != end_local.date():
        return False

    # Workdays only
    if start_local.weekday() not in WORK_DAYS:
        return False

    st = start_local.time()
    en = end_local.time()

    if st < WORK_START:
        return False
    if en > WORK_END:
        return False

    return True


def _has_overlap_active(*, room_id, start, end, exclude_id=None) -> bool:
    qs = (
        Booking.objects.filter(room_id=room_id)
        .exclude(status__in=[Booking.Status.REJECTED, Booking.Status.CANCELLED])
        .filter(start__lt=end, end__gt=start)
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


def _get_room_ids_from_query(request) -> list[int]:
    rooms_raw = (request.GET.get("rooms") or "").strip()
    if not rooms_raw:
        return []

    room_ids = []
    for x in rooms_raw.split(","):
        x = x.strip()
        if x.isdigit():
            room_ids.append(int(x))
    return room_ids


# ===========================
# API
# ===========================
@login_required
@require_http_methods(["GET"])
def api_rooms(request):
    rooms = MeetingRoom.objects.all().order_by("name")
    return JsonResponse(
        [{"id": r.id, "name": r.name, "capacity": r.capacity} for r in rooms],
        safe=False,
    )


@login_required
@require_http_methods(["GET", "POST"])
def api_bookings(request):
    if request.method == "GET":
        start = request.GET.get("start")
        end = request.GET.get("end")

        qs = Booking.objects.select_related("room", "user")
        room_ids = _get_room_ids_from_query(request)

        if start and end:
            start_dt = _ensure_aware(parse_datetime(start))
            end_dt = _ensure_aware(parse_datetime(end))
            if start_dt and end_dt:
                qs = qs.filter(start__lt=end_dt, end__gt=start_dt)

        if room_ids:
            qs = qs.filter(room_id__in=room_ids)

        if not request.user.is_staff:
            qs = qs.filter(Q(status=Booking.Status.APPROVED) | Q(user=request.user))

        events = []
        for b in qs:
            title = f"{b.room.name} ({b.get_status_display()})"
            if getattr(b, "title", ""):
                title = b.title

            events.append(
                {
                    "id": b.id,
                    "title": title,
                    "start": b.start.isoformat(),
                    "end": b.end.isoformat(),
                    "allDay": False,
                    "color": _booking_color(b.status),
                    "extendedProps": {
                        "roomId": b.room_id,
                        "roomName": b.room.name,
                        "status": b.status,
                        "statusLabel": b.get_status_display(),
                        "isMine": b.user_id == request.user.id,
                        "bookedBy": b.user.username,
                    },
                }
            )

        return JsonResponse(events, safe=False)

    # POST: create booking
    payload = _parse_body_json(request)
    if payload is None:
        return _json_error("Bad JSON", status=400)

    room_id = _parse_int(payload.get("room_id"), default=None)
    if room_id is None:
        room_id = _parse_int(payload.get("roomId"), default=None)

    start = _ensure_aware(parse_datetime(payload.get("start")))
    end = _ensure_aware(parse_datetime(payload.get("end")))

    if room_id is None or not start or not end:
        return _json_error("Missing/invalid fields", status=400)

    room = MeetingRoom.objects.filter(id=room_id).first()
    if not room:
        return _json_error("Room not found", status=404)

    if not _is_within_working_hours(start, end):
        return _json_error(
            "Бронювання дозволено тільки в робочий час (Пн–Пт, 08:00–20:00).",
            status=400,
        )

    if _has_overlap_active(room_id=room_id, start=start, end=end):
        return _json_error("Цей час уже зайнятий для вибраної переговорної.", status=400)

    booking = Booking(
        room=room,
        user=request.user,
        start=start,
        end=end,
        status=Booking.Status.PENDING,
    )

    if hasattr(booking, "title"):
        booking.title = (payload.get("title") or "").strip()
    if hasattr(booking, "comment"):
        booking.comment = (payload.get("comment") or "").strip()

    try:
        booking.full_clean()
        booking.save()
    except Exception as e:
        return _json_error(str(e), status=400)

    return _json_ok({"id": booking.id})


@login_required
@require_http_methods(["POST"])
def api_booking_cancel(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    if booking.user_id != request.user.id and not request.user.is_staff:
        return HttpResponseForbidden("Недостатньо прав")

    if booking.status not in [Booking.Status.CANCELLED, Booking.Status.REJECTED]:
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])

    return _json_ok()


@staff_member_required
@require_http_methods(["POST"])
def api_booking_approve(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    if booking.status != Booking.Status.PENDING:
        return _json_error("Not pending", status=400)

    if not _is_within_working_hours(booking.start, booking.end):
        return _json_error(
            "Не можна підтвердити бронювання поза робочим часом (Пн–Пт, 08:00–20:00).",
            status=400,
        )

    if _has_overlap_active(
        room_id=booking.room_id,
        start=booking.start,
        end=booking.end,
        exclude_id=booking.id,
    ):
        return _json_error("Цей час уже зайнятий для вибраної переговорної.", status=400)

    booking.status = Booking.Status.APPROVED

    if hasattr(booking, "approved_by_id"):
        booking.approved_by = request.user
    if hasattr(booking, "approved_at"):
        booking.approved_at = timezone.now()

    booking.save()
    return _json_ok()


@staff_member_required
@require_http_methods(["POST"])
def api_booking_reject(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    if booking.status != Booking.Status.PENDING:
        return _json_error("Not pending", status=400)

    booking.status = Booking.Status.REJECTED

    if hasattr(booking, "approved_by_id"):
        booking.approved_by = request.user
    if hasattr(booking, "approved_at"):
        booking.approved_at = timezone.now()

    booking.save()
    return _json_ok()
