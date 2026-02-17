from datetime import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Room(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Booking(models.Model):
    """
    Бронювання кімнати.

    Робочий час: 08:00–20:00
    Перетини заборонені для активних бронювань (PENDING + APPROVED)
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Очікує"
        APPROVED = "APPROVED", "Підтверджено"
        REJECTED = "REJECTED", "Відхилено"

    WORK_START = time(8, 0)
    WORK_END = time(20, 0)

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bookings")

    start = models.DateTimeField("Початок")
    end = models.DateTimeField("Кінець")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_bookings",
    )

    status = models.CharField(
        "Статус",
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="approved_bookings",
        on_delete=models.SET_NULL,
    )
    approved_at = models.DateTimeField("Підтверджено о", null=True, blank=True)

    class Meta:
        ordering = ["-start"]

    def clean(self):
        # базове
        if self.end <= self.start:
            raise ValidationError("Кінець має бути після початку.")

        # не даємо тягнути бронювання на інший день (спрощує життя і календар)
        if self.start.date() != self.end.date():
            raise ValidationError("Бронювання має бути в межах одного дня.")

        # робочий час
        s = self.start.astimezone().time()
        e = self.end.astimezone().time()

        if not (self.WORK_START <= s < self.WORK_END):
            raise ValidationError("Початок має бути в робочий час (08:00–20:00).")
        if not (self.WORK_START < e <= self.WORK_END):
            raise ValidationError("Кінець має бути в робочий час (08:00–20:00).")

        # перетин: перевіряємо тільки активні бронювання
        qs = Booking.objects.filter(room=self.room).filter(
            Q(status=Booking.Status.PENDING) | Q(status=Booking.Status.APPROVED)
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        overlap = qs.filter(start__lt=self.end, end__gt=self.start).exists()
        if overlap:
            raise ValidationError("Цей час уже зайнятий для вибраної кімнати.")

    def __str__(self) -> str:
        return f"{self.room} | {self.start:%Y-%m-%d %H:%M}—{self.end:%H:%M} | {self.get_status_display()}"
