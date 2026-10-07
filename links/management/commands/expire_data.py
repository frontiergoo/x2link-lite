from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from links.models import Audit, ClickEvent, ConversionJob, DailyMetric


class Command(BaseCommand):
    help = "保持期限を過ぎたデータを削除します。設定の版と公開別名は保持します。"

    def handle(self, *args, **options):
        now = timezone.now()
        events, _ = ClickEvent.objects.filter(
            created_at__lt=now - timedelta(days=30), processed=True
        ).delete()
        audits, _ = Audit.objects.filter(
            created_at__lt=now - timedelta(days=180)
        ).delete()
        jobs, _ = ConversionJob.objects.filter(
            created_at__lt=now - timedelta(days=7)
        ).delete()
        metrics, _ = DailyMetric.objects.filter(
            date__lt=(now - timedelta(days=397)).date()
        ).delete()
        self.stdout.write(
            f"詳細イベント{events}件、監査{audits}件、本文結果{jobs}件、集計{metrics}件を削除しました。"
        )
