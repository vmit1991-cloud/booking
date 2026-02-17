from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


# ---------------------------
# meeting rooms
# ---------------------------
class MeetingRoom(models.Model):
    name = models.CharField("Назва", max_length=120, unique=True)
    capacity = models.PositiveIntegerField("Кількість місць")

    has_projector = models.BooleanField("Проектор", default=False)
    has_speakerphone = models.BooleanField("Спікерфон", default=False)
    has_tv = models.BooleanField("Телевізор / екран", default=False)
    has_whiteboard = models.BooleanField("Маркерна дошка", default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Переговорна кімната"
        verbose_name_plural = "Переговорні кімнати"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.capacity} місць)"


# ---------------------------
# bookings
# ---------------------------
class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Очікує підтвердження"
        APPROVED = "APPROVED", "Підтверджено"
        REJECTED = "REJECTED", "Відхилено"
        CANCELLED = "CANCELLED", "Скасовано"

    room = models.ForeignKey(
        MeetingRoom,
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookings",
    )

    start = models.DateTimeField("Початок")
    end = models.DateTimeField("Кінець")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start"]

    def clean(self):
        # базова перевірка дат
        if self.end <= self.start:
            raise ValidationError("Кінець має бути після початку.")

        # беремо бронювання цієї ж кімнати
        # і не враховуємо відхилені та скасовані
        active_statuses = [self.Status.PENDING, self.Status.APPROVED]

        qs = Booking.objects.filter(
            room=self.room,
            status__in=active_statuses,
        )

        # якщо редагування — виключаємо сам запис
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        # перевірка перетину по часу
        # start < існуючий end  AND  end > існуючий start
        has_overlap = qs.filter(
            Q(start__lt=self.end) & Q(end__gt=self.start)
        ).exists()

        if has_overlap:
            raise ValidationError(
                "Цей час уже зайнятий для вибраної переговорної."
            )

    def __str__(self):
        return f"{self.room} | {self.start} - {self.end} | {self.user} | {self.status}"
