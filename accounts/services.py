from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import MeetingRoom

User = get_user_model()

MIN_PASSWORD_LEN = 6


@dataclass
class CreateUserResult:
    ok: bool
    error: str | None = None


# ---------------------------
# users
# ---------------------------
def _password_error(p1: str, p2: str) -> str | None:
    if p1 != p2:
        return "Паролі не співпадають."
    if len(p1) < MIN_PASSWORD_LEN:
        return f"Пароль має бути мінімум {MIN_PASSWORD_LEN} символів."

    try:
        validate_password(p1)
    except ValidationError as e:
        return "; ".join(e.messages)

    return None


def create_user_by_admin(
    *,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password1: str,
    password2: str,
    is_staff: bool,
    is_superuser: bool,
    is_active: bool,
) -> CreateUserResult:
    username = (username or "").strip()

    if not username:
        return CreateUserResult(False, "Username обовʼязковий.")
    if User.objects.filter(username=username).exists():
        return CreateUserResult(False, "Такий username вже існує.")

    err = _password_error(password1 or "", password2 or "")
    if err:
        return CreateUserResult(False, err)

    user = User(
        username=username,
        email=(email or "").strip(),
        first_name=(first_name or "").strip(),
        last_name=(last_name or "").strip(),
        is_staff=is_staff,
        is_superuser=is_superuser,
        is_active=is_active,
    )
    user.set_password(password1)
    user.save()

    return CreateUserResult(True)


# ---------------------------
# rooms
# ---------------------------
def _parse_int(value, default: int = 0) -> int:
    try:
        return int((value or "").strip())
    except (TypeError, ValueError):
        return default


def update_meeting_room_from_post(room: MeetingRoom, post) -> None:
    room.name = (post.get("name") or "").strip()
    room.capacity = _parse_int(post.get("capacity"), default=0)

    # чекбокси просто: є ключ -> True
    room.has_projector = "has_projector" in post
    room.has_speakerphone = "has_speakerphone" in post
    room.has_tv = "has_tv" in post
    room.has_whiteboard = "has_whiteboard" in post
