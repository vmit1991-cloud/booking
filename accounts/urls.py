from django.urls import path
from . import views
from . import api

urlpatterns = [
    # ===========================
    # PUBLIC
    # ===========================
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("calendar/", views.calendar_view, name="calendar"),

    # ===========================
    # ADMIN: ROOMS
    # ===========================
    path("admin/rooms/", views.admin_rooms, name="admin_rooms"),
    path("admin/rooms/<int:room_id>/edit/", views.admin_room_edit, name="admin_room_edit"),
    path("admin/rooms/<int:room_id>/delete/", views.admin_room_delete, name="admin_room_delete"),

    # ===========================
    # ADMIN: BOOKINGS
    # ===========================
    path("admin/bookings/pending/", views.admin_pending_bookings, name="admin_pending_bookings"),

    # ===========================
    # ADMIN: USERS
    # ===========================
    path("admin/users/", views.admin_users, name="admin_users"),
    path("admin/users/<int:user_id>/", views.admin_user_detail, name="admin_user_detail"),
    path("admin/users/<int:user_id>/toggle-active/", views.admin_user_toggle_active, name="admin_user_toggle_active"),
    path("admin/users/<int:user_id>/set-password/", views.admin_user_set_password, name="admin_user_set_password"),
    path("admin/users/create/", views.admin_create_user, name="admin_create_user"),

    # ===========================
    # API
    # ===========================
    path("api/rooms/", api.api_rooms, name="api_rooms"),
    path("api/bookings/", api.api_bookings, name="api_bookings"),
    path("api/bookings/<int:booking_id>/approve/", api.api_booking_approve, name="api_booking_approve"),
    path("api/bookings/<int:booking_id>/reject/", api.api_booking_reject, name="api_booking_reject"),
    path("api/bookings/<int:booking_id>/cancel/", api.api_booking_cancel, name="api_booking_cancel"),
]
