from django.db import migrations
import os


def create_admin(apps, schema_editor):
    # Створюємо адміна тільки на Render, локально не чіпаємо
    if not os.environ.get("RENDER"):
        return

    User = apps.get_model("auth", "User")

    username = os.environ.get("DJANGO_ADMIN_USER", "admin")
    email = os.environ.get("DJANGO_ADMIN_EMAIL", "admin@example.com")
    password = os.environ.get("DJANGO_ADMIN_PASSWORD", "p@ssw0rdforbooking")

    if User.objects.filter(username=username).exists():
        return

    User.objects.create_superuser(username=username, email=email, password=password)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_alter_booking_status"),
    ]

    operations = [
        migrations.RunPython(create_admin),
    ]
