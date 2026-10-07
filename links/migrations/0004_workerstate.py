# Djangoによるデータベース変更定義。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0003_alter_link_tags"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkerState",
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
                ("name", models.CharField(max_length=64, unique=True)),
                ("last_run", models.DateTimeField(null=True)),
                ("processed_total", models.PositiveBigIntegerField(default=0)),
            ],
        ),
    ]
