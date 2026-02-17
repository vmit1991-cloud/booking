import json

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from .models import Booking, MeetingRoom


# ---------------------------
# helpers
# ---------------------------
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
    # просто щоб в календарі було видно статус
    if status == Booking.Status.APPROVED:
        return "#2e7d32"
    if status == Booking.Status.PENDING:
        return "#6c757d"
    if status == Booking.Status.CANCELLED:
        return "#f57c00"
    return "#b71c1c"  # rejected / unknown


def _has_overlap_active(*, room_id, start, end, exclude_id=None) -> bool:
    # перевіряємо перетин тільки з "живими" бронюваннями (pending/approved)
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


# ---------------------------
# api: rooms
# ---------------------------
@login_required
@require_http_methods(["GET"])
def api_rooms(request):
    rooms = MeetingRoom.objects.all().order_by("name")
    return JsonResponse(
        [{"id": r.id, "name": r.name, "capacity": r.capacity} for r in rooms],
        safe=False,
    )


# ---------------------------
# api: bookings
# ---------------------------
@login_required
@require_http_methods(["GET", "POST"])
def api_bookings(request):
    # GET  -> події для FullCalendar
    # POST -> створення бронювання (pending)
    if request.method == "GET":
        start = request.GET.get("start")
        end = request.GET.get("end")

        qs = Booking.objects.select_related("room", "user")
        room_ids = _get_room_ids_from_query(request)

        # фільтр по вікну календаря (FullCalendar передає start/end)
        if start and end:
            start_dt = parse_datetime(start)
            end_dt = parse_datetime(end)
            if start_dt and end_dt:
                qs = qs.filter(start__lt=end_dt, end__gt=start_dt)

        if room_ids:
            qs = qs.filter(room_id__in=room_ids)

        # видимість:
        # - staff бачить все
        # - звичайний бачить затверджені бронювання всіх + свої (будь-який статус)
        if not request.user.is_staff:
            qs = qs.filter(Q(status=Booking.Status.APPROVED) | Q(user=request.user))

        events = []
        for b in qs:
            title = f"{b.room.name} ({b.get_status_display()})"

            # якщо в моделі є поле title — можна показувати його
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

    # --- POST ---
    payload = _parse_body_json(request)
    if payload is None:
        return _json_error("Bad JSON", status=400)

    # на всяк: підтримка room_id і roomId
    room_id = _parse_int(payload.get("room_id"), default=None)
    if room_id is None:
        room_id = _parse_int(payload.get("roomId"), default=None)

    start = parse_datetime(payload.get("start"))
    end = parse_datetime(payload.get("end"))

    if room_id is None or not start or not end:
        return _json_error("Missing/invalid fields", status=400)

    room = MeetingRoom.objects.filter(id=room_id).first()
    if not room:
        return _json_error("Room not found", status=404)

    if _has_overlap_active(room_id=room_id, start=start, end=end):
        return _json_error("Цей час уже зайнятий для вибраної переговорної.", status=400)

    booking = Booking(
        room=room,
        user=request.user,
        start=start,
        end=end,
        status=Booking.Status.PENDING,
    )

    # ці поля можуть бути, а можуть і не бути (залежить від твоєї моделі)
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
    # staff може скасувати будь-яке, користувач — тільки своє
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

    if _has_overlap_active(
        room_id=booking.room_id,
        start=booking.start,
        end=booking.end,
        exclude_id=booking.id,
    ):
        return _json_error("Цей час уже зайнятий для вибраної переговорної.", status=400)

    booking.status = Booking.Status.APPROVED

    # якщо є поля "хто підтвердив" і "коли"
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
