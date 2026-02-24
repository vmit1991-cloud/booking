import json
from datetime import time
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from .models import Booking, MeetingRoom

WORK_DAYS = {0, 1, 2, 3, 4}
WORK_START = time(8, 0)
WORK_END = time(20, 0)


def _json_ok(extra: dict[str, Any] | None = None) -> JsonResponse:
    data: dict[str, Any] = {"ok": True}
    if extra:
        data.update(extra)
    return JsonResponse(data)


def _json_error(message: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _parse_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_body_json(request) -> dict[str, Any] | None:
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return None


def _ensure_aware(dt):
    if dt is None:
        return None
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt, timezone.get_current_timezone())


def _to_local(dt):
    dt = _ensure_aware(dt)
    if dt is None:
        return None
    return timezone.localtime(dt)


def _is_within_working_hours(start, end) -> bool:
    if not start or not end:
        return False
    start_local = _to_local(start)
    end_local = _to_local(end)
    if not start_local or not end_local:
        return False
    if end_local <= start_local:
        return False
    if start_local.date() != end_local.date():
        return False
    if start_local.weekday() not in WORK_DAYS:
        return False
    st = start_local.time()
    en = end_local.time()
    if st < WORK_START:
        return False
    if en > WORK_END:
        return False
    return True


def _status_if_exists(name: str) -> str | None:
    return getattr(Booking.Status, name, None)


def _excluded_statuses_for_overlap() -> list[str]:
    excluded: list[str] = []
    s = _status_if_exists("REJECTED")
    if s:
        excluded.append(s)
    s = _status_if_exists("CANCELLED")
    if s:
        excluded.append(s)
    return excluded


def _has_overlap_active(*, room_id: int, start, end, exclude_id: int | None = None) -> bool:
    qs = (
        Booking.objects.filter(room_id=room_id)
        .exclude(status__in=_excluded_statuses_for_overlap())
        .filter(start__lt=end, end__gt=start)
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


def _get_room_ids_from_query(request) -> list[int]:
    rooms_raw = (request.GET.get("rooms") or "").strip()
    if not rooms_raw:
        return []
    out: list[int] = []
    for x in rooms_raw.split(","):
        x = x.strip()
        if x.isdigit():
            out.append(int(x))
    return out


def _booking_color(status: str) -> str:
    # залишаємо кольори як були, але без "approve flow"
    if status == Booking.Status.APPROVED:
        return "#2e7d32"
    cancelled = _status_if_exists("CANCELLED")
    if cancelled and status == cancelled:
        return "#f57c00"
    rejected = _status_if_exists("REJECTED")
    if rejected and status == rejected:
        return "#b71c1c"
    pending = _status_if_exists("PENDING")
    if pending and status == pending:
        return "#6c757d"
    return "#6c757d"


def _event_title(b: Booking) -> str:
    # прибрали "(Підтверджено)" і будь-які статуси з title
    custom_title = (getattr(b, "title", "") or "").strip()
    if custom_title:
        return custom_title
    return b.room.name


def _room_payload(r: MeetingRoom) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "capacity": r.capacity,
        "has_projector": getattr(r, "has_projector", False),
        "has_speakerphone": getattr(r, "has_speakerphone", False),
        "has_tv": getattr(r, "has_tv", False),
        "has_whiteboard": getattr(r, "has_whiteboard", False),
    }


def _can_cancel_booking(b: Booking, user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return (b.user_id == user.id) or bool(getattr(user, "is_staff", False))


@login_required
@require_http_methods(["GET"])
def api_rooms(request):
    rooms = MeetingRoom.objects.all().order_by("name")
    return JsonResponse([_room_payload(r) for r in rooms], safe=False)


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

        events: list[dict[str, Any]] = []
        for b in qs:
            can_cancel = _can_cancel_booking(b, request.user)
            events.append(
                {
                    "id": b.id,
                    "title": _event_title(b),
                    "start": b.start.isoformat(),
                    "end": b.end.isoformat(),
                    "allDay": False,
                    "color": _booking_color(b.status),
                    "canCancel": can_cancel,
                    "bookedBy": b.user.username,
                    "extendedProps": {
                        "id": b.id,
                        "roomId": b.room_id,
                        "roomName": b.room.name,
                        "isMine": b.user_id == request.user.id,
                        "bookedBy": b.user.username,
                        "canCancel": can_cancel,
                        "status": b.status,
                        "statusLabel": b.get_status_display(),
                    },
                }
            )
        return JsonResponse(events, safe=False)

    payload = _parse_body_json(request)
    if payload is None:
        return _json_error("Bad JSON", status=400)

    room_id = _parse_int(payload.get("room_id"), default=None)
    if room_id is None:
        room_id = _parse_int(payload.get("roomId"), default=None)

    start_raw = payload.get("start")
    end_raw = payload.get("end")
    start = _ensure_aware(parse_datetime(str(start_raw or "")))
    end = _ensure_aware(parse_datetime(str(end_raw or "")))

    if room_id is None or not start or not end:
        return _json_error("Missing/invalid fields", status=400)

    now = timezone.now()
    if start < now:
        return _json_error("Не можна створювати бронювання в минулому.", status=400)

    if end <= start:
        return _json_error("Кінець має бути пізніше за початок.", status=400)

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
        status=Booking.Status.APPROVED,
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
    if not _can_cancel_booking(booking, request.user):
        return HttpResponseForbidden("Недостатньо прав")
    booking.delete()
    return _json_ok()