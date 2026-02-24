from __future__ import annotations

from typing import Any

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import MeetingRoom

User = get_user_model()

MIN_PASSWORD_LEN = 6


def _str(post: dict[str, Any], name: str) -> str:
    return (post.get(name) or "").strip()


def _bool_from_post(post: dict[str, Any], name: str) -> bool:
    return name in post


def _parse_capacity(value: Any) -> int:
    s = (value or "").strip()
    try:
        n = int(s)
    except (TypeError, ValueError):
        return 0
    return n


def _room_flags_from_post(post: dict[str, Any]) -> dict[str, bool]:
    return {
        "has_projector": _bool_from_post(post, "has_projector"),
        "has_speakerphone": _bool_from_post(post, "has_speakerphone"),
        "has_tv": _bool_from_post(post, "has_tv"),
        "has_whiteboard": _bool_from_post(post, "has_whiteboard"),
    }


def _password_error(password1: str, password2: str) -> str | None:
    if password1 != password2:
        return "Паролі не співпадають."
    if len(password1) < MIN_PASSWORD_LEN:
        return f"Пароль має бути мінімум {MIN_PASSWORD_LEN} символів."

    try:
        validate_password(password1)
    except ValidationError as e:
        return " ".join(e.messages)

    return None


def _safe_next_url(request: HttpRequest, default_url_name: str) -> str:
    nxt = (request.GET.get("next") or "").strip()
    if nxt and url_has_allowed_host_and_scheme(
        url=nxt,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return nxt
    return reverse(default_url_name)


def _room_form_error(name: str, capacity: int) -> str | None:
    if not name:
        return "Назва переговорної обовʼязкова."
    if capacity <= 0:
        return "Місткість має бути більше 0."
    if MeetingRoom.objects.filter(name__iexact=name).exists():
        return "Переговорна з такою назвою вже існує."
    return None


def home(request: HttpRequest) -> HttpResponse:
    return redirect("calendar")


@ensure_csrf_cookie
@login_required
def calendar_view(request: HttpRequest) -> HttpResponse:
    return render(request, "calendar/index.html")


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("calendar")

    error: str | None = None

    if request.method == "POST":
        username = _str(request.POST, "username")
        password = request.POST.get("password") or ""

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(_safe_next_url(request, "calendar"))

        error = "Невірний логін або пароль"

    next_url = request.GET.get("next") or ""
    return render(request, "accounts/login.html", {"error": error, "next": next_url})


@login_required
@require_http_methods(["POST"])
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("login")


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_rooms(request: HttpRequest) -> HttpResponse:
    error: str | None = None

    if request.method == "POST":
        name = _str(request.POST, "name")
        capacity = _parse_capacity(request.POST.get("capacity"))

        error = _room_form_error(name, capacity)
        if not error:
            MeetingRoom.objects.create(
                name=name,
                capacity=capacity,
                **_room_flags_from_post(request.POST),
            )
            return redirect("admin_rooms")

    rooms = MeetingRoom.objects.all().order_by("name")
    return render(request, "admin/rooms.html", {"rooms": rooms, "error": error})


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_room_edit(request: HttpRequest, room_id: int) -> HttpResponse:
    room = get_object_or_404(MeetingRoom, id=room_id)
    error: str | None = None

    if request.method == "POST":
        name = _str(request.POST, "name")
        capacity = _parse_capacity(request.POST.get("capacity"))

        if not name:
            error = "Назва переговорної обовʼязкова."
        elif capacity <= 0:
            error = "Місткість має бути більше 0."
        elif MeetingRoom.objects.filter(name__iexact=name).exclude(id=room.id).exists():
            error = "Переговорна з такою назвою вже існує."

        if not error:
            room.name = name
            room.capacity = capacity

            flags = _room_flags_from_post(request.POST)
            room.has_projector = flags["has_projector"]
            room.has_speakerphone = flags["has_speakerphone"]
            room.has_tv = flags["has_tv"]
            room.has_whiteboard = flags["has_whiteboard"]

            room.save()
            return redirect("admin_rooms")

    return render(request, "admin/room_edit.html", {"room": room, "error": error})


@staff_member_required
@require_http_methods(["POST"])
def admin_room_delete(request: HttpRequest, room_id: int) -> HttpResponse:
    room = get_object_or_404(MeetingRoom, id=room_id)
    room.delete()
    return redirect("admin_rooms")


@staff_member_required
@require_http_methods(["GET"])
def admin_users(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    active = request.GET.get("active")

    users = User.objects.all().order_by("username")

    if q:
        users = users.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )

    if active in ("0", "1"):
        users = users.filter(is_active=(active == "1"))

    return render(
        request,
        "admin/users.html",
        {"users": users, "q": q, "active": active},
    )


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_create_user(request: HttpRequest) -> HttpResponse:
    error: str | None = None

    if request.method == "POST":
        username = _str(request.POST, "username")
        email = _str(request.POST, "email")
        first_name = _str(request.POST, "first_name")
        last_name = _str(request.POST, "last_name")

        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        is_staff = _bool_from_post(request.POST, "is_staff")
        is_superuser = _bool_from_post(request.POST, "is_superuser")
        is_active = _bool_from_post(request.POST, "is_active")

        if not username:
            error = "Username обовʼязковий."
        elif User.objects.filter(username=username).exists():
            error = "Такий username вже існує."
        else:
            error = _password_error(password1, password2)

        if not error:
            user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_staff=is_staff,
                is_superuser=is_superuser,
                is_active=is_active,
            )
            user.set_password(password1)
            user.save()
            return redirect("admin_users")

    return render(request, "admin/user_create.html", {"error": error})


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_user_detail(request: HttpRequest, user_id: int) -> HttpResponse:
    u = get_object_or_404(User, id=user_id)

    error: str | None = None
    saved = False

    if request.method == "POST":
        u.email = _str(request.POST, "email")
        u.first_name = _str(request.POST, "first_name")
        u.last_name = _str(request.POST, "last_name")

        requested_staff = _bool_from_post(request.POST, "is_staff")
        if u.id == request.user.id and not requested_staff:
            error = "Не можна прибрати собі staff-доступ."
        else:
            u.is_staff = requested_staff

        if not error:
            u.save(update_fields=["email", "first_name", "last_name", "is_staff"])
            saved = True

    return render(request, "admin/user_detail.html", {"u": u, "error": error, "saved": saved})


@staff_member_required
@require_http_methods(["POST"])
def admin_user_toggle_active(request: HttpRequest, user_id: int) -> HttpResponse:
    u = get_object_or_404(User, id=user_id)

    if u.id == request.user.id:
        return HttpResponseForbidden("Не можна деактивувати самого себе.")

    u.is_active = not u.is_active
    u.save(update_fields=["is_active"])

    return redirect("admin_user_detail", user_id=u.id)


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_user_set_password(request: HttpRequest, user_id: int) -> HttpResponse:
    u = get_object_or_404(User, id=user_id)
    error: str | None = None

    if request.method == "POST":
        p1 = request.POST.get("password1") or ""
        p2 = request.POST.get("password2") or ""

        error = _password_error(p1, p2)
        if not error:
            u.set_password(p1)
            u.save()
            return redirect("admin_user_detail", user_id=u.id)

    return render(request, "admin/user_set_password.html", {"u": u, "error": error})
