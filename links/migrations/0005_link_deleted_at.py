# Djangoによるデータベース変更定義。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0004_workerstate"),
    ]

    operations = [
        migrations.AddField(
            model_name="link",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="削除日時"),
        ),
    ]
