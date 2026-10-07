# Djangoによるデータベース変更定義。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0006_clickevent_response_status_clickevent_rule_version_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="audit",
            name="changes",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="audit",
            name="version",
            field=models.PositiveIntegerField(null=True),
        ),
    ]
