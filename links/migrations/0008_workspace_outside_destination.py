# Djangoによるデータベース変更定義。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0007_audit_changes_audit_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="outside_destination",
            field=models.URLField(
                blank=True, max_length=4096, verbose_name="既定の期間外転送先"
            ),
        ),
    ]
