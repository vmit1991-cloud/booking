from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import Booking, MeetingRoom

User = get_user_model()

MIN_PASSWORD_LEN = 6


# ---------------------------
# public
# ---------------------------
def home(request):
    return redirect("calendar")


@ensure_csrf_cookie
@login_required
def calendar_view(request):
    return render(request, "calendar/index.html")


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("calendar")

    error = None

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("calendar")

        error = "Невірний логін або пароль"

    return render(request, "accounts/login.html", {"error": error})


@login_required
@require_http_methods(["POST"])
def logout_view(request):
    # вихід має бути тільки POST
    logout(request)
    return redirect("login")


# ---------------------------
# helpers
# ---------------------------
def _bool_from_post(post, name: str) -> bool:
    return name in post


def _room_flags_from_post(post) -> dict:
    # чекбокси -> boolean поля
    return {
        "has_projector": _bool_from_post(post, "has_projector"),
        "has_speakerphone": _bool_from_post(post, "has_speakerphone"),
        "has_tv": _bool_from_post(post, "has_tv"),
        "has_whiteboard": _bool_from_post(post, "has_whiteboard"),
    }


def _parse_capacity(value) -> int:
    value = (value or "").strip()
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------------------
# admin: rooms
# ---------------------------
@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_rooms(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        capacity = _parse_capacity(request.POST.get("capacity"))

      
        MeetingRoom.objects.create(
            name=name,
            capacity=capacity,
            **_room_flags_from_post(request.POST),
        )
        return redirect("admin_rooms")

    rooms = MeetingRoom.objects.all().order_by("name")
    return render(request, "admin/rooms.html", {"rooms": rooms})


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_room_edit(request, room_id):
    room = get_object_or_404(MeetingRoom, id=room_id)

    if request.method == "POST":
        room.name = (request.POST.get("name") or "").strip()
        room.capacity = _parse_capacity(request.POST.get("capacity"))

        flags = _room_flags_from_post(request.POST)
        room.has_projector = flags["has_projector"]
        room.has_speakerphone = flags["has_speakerphone"]
        room.has_tv = flags["has_tv"]
        room.has_whiteboard = flags["has_whiteboard"]

        room.save()
        return redirect("admin_rooms")

    return render(request, "admin/room_edit.html", {"room": room})


@staff_member_required
@require_http_methods(["POST"])
def admin_room_delete(request, room_id):
    room = get_object_or_404(MeetingRoom, id=room_id)
    room.delete()
    return redirect("admin_rooms")


# ---------------------------
# admin: users
# ---------------------------
@staff_member_required
@require_http_methods(["GET"])
def admin_users(request):
    q = (request.GET.get("q") or "").strip()
    active = request.GET.get("active")  # "1" / "0" / None

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

    return render(request, "admin/users.html", {"users": users, "q": q, "active": active})


def _password_error(password1: str, password2: str) -> str | None:
    if password1 != password2:
        return "Паролі не співпадають."
    if len(password1) < MIN_PASSWORD_LEN:
        return f"Пароль має бути мінімум {MIN_PASSWORD_LEN} символів."

    try:
        validate_password(password1)
    except ValidationError as e:
        # Django повертає список повідомлень
        return " ".join(e.messages)

    return None


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_create_user(request):
    error = None

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip()
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()

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
def admin_user_detail(request, user_id):
    user = get_object_or_404(User, id=user_id)

    error = None
    saved = False

    if request.method == "POST":
        user.email = (request.POST.get("email") or "").strip()
        user.first_name = (request.POST.get("first_name") or "").strip()
        user.last_name = (request.POST.get("last_name") or "").strip()

        # щоб адмін випадково не забрав у себе staff-доступ
        if user.id == request.user.id and not _bool_from_post(request.POST, "is_staff"):
            error = "Не можна прибрати собі staff-доступ."
        else:
            user.is_staff = _bool_from_post(request.POST, "is_staff")

        if not error:
            user.save(update_fields=["email", "first_name", "last_name", "is_staff"])
            saved = True

    return render(request, "admin/user_detail.html", {"u": user, "error": error, "saved": saved})


@staff_member_required
@require_http_methods(["POST"])
def admin_user_toggle_active(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if user.id == request.user.id:
        return HttpResponseForbidden("Не можна деактивувати самого себе.")

    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])

    return redirect("admin_user_detail", user_id=user.id)


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_user_set_password(request, user_id):
    user = get_object_or_404(User, id=user_id)

    error = None

    if request.method == "POST":
        p1 = request.POST.get("password1") or ""
        p2 = request.POST.get("password2") or ""

        error = _password_error(p1, p2)
        if not error:
            user.set_password(p1)
            user.save()
            return redirect("admin_user_detail", user_id=user.id)

    return render(request, "admin/user_set_password.html", {"u": user, "error": error})


# ---------------------------
# admin: pending bookings
# ---------------------------
@staff_member_required
@require_http_methods(["GET"])
def admin_pending_bookings(request):
    pending = (
        Booking.objects.select_related("room", "user")
        .filter(status=Booking.Status.PENDING)
        .order_by("start")
    )
    return render(request, "admin/pending_bookings.html", {"pending": pending})
