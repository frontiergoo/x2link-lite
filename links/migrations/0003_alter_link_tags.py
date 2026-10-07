# Djangoによるデータベース変更定義。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0002_loginattempt"),
    ]

    operations = [
        migrations.AlterField(
            model_name="link",
            name="tags",
            field=models.JSONField(blank=True, default=list, verbose_name="タグ"),
        ),
    ]
