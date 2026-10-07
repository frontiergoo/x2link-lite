# Djangoによるデータベース変更定義。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoginAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=64, unique=True)),
                ("failures", models.PositiveIntegerField(default=0)),
                ("locked_until", models.DateTimeField(null=True)),
            ],
        ),
    ]
