from django.utils import timezone


def assert_no_conflict(BookingModel, *, room_id, start, end, exclude_id=None):
   
    if not start or not end:
        raise ValueError("Start/end required")
    if start >= end:
        raise ValueError("Invalid time range")
    if start < timezone.now():
        raise ValueError("Cannot book in the past")

    qs = BookingModel.objects.filter(
        room_id=room_id,
        status=BookingModel.Status.APPROVED,
        start__lt=end,
        end__gt=start,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)

    if qs.exists():
        raise ValueError("Time conflict with existing approved booking")
