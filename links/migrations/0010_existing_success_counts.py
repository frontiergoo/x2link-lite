# 旧形式の集計は302応答だけを対象としていたため、成功数を補完する。
from django.db import migrations
from django.db.models import F


def fill_successes(apps, schema_editor):
    apps.get_model("links", "DailyMetric").objects.all().update(successes=F("requests"))


class Migration(migrations.Migration):
    dependencies = [("links", "0009_alter_clickevent_device_alter_dailymetric_device")]
    operations = [migrations.RunPython(fill_successes, migrations.RunPython.noop)]
