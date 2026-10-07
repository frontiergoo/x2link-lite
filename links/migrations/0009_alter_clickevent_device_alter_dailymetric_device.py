# Djangoによるデータベース変更定義。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0008_workspace_outside_destination"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clickevent",
            name="device",
            field=models.CharField(
                choices=[
                    ("unknown", "不明"),
                    ("desktop", "PC"),
                    ("mobile", "スマートフォン"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="dailymetric",
            name="device",
            field=models.CharField(
                choices=[
                    ("unknown", "不明"),
                    ("desktop", "PC"),
                    ("mobile", "スマートフォン"),
                ],
                max_length=16,
            ),
        ),
    ]
