# Djangoによるデータベース変更定義。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0005_link_deleted_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="clickevent",
            name="response_status",
            field=models.PositiveSmallIntegerField(default=302),
        ),
        migrations.AddField(
            model_name="clickevent",
            name="rule_version",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="dailymetric",
            name="successes",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name="clickevent",
            index=models.Index(
                fields=["processed", "created_at"], name="event_pending_time"
            ),
        ),
    ]
