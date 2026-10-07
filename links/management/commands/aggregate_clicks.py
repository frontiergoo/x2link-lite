from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from links.models import ClickEvent, DailyMetric, WorkerState


class Command(BaseCommand):
    help = "クリックイベントを重複なく日次集計します。1分ごとの実行を推奨します。"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10000)

    def handle(self, *args, **options):
        count = 0
        with transaction.atomic():
            events = (
                ClickEvent.objects.select_for_update()
                .filter(processed=False)
                .order_by("created_at")[: options["limit"]]
            )
            for event in events:
                metric, _ = DailyMetric.objects.get_or_create(
                    link=event.link,
                    date=timezone.localdate(event.created_at),
                    device=event.device,
                    referrer=event.referrer,
                )
                DailyMetric.objects.filter(pk=metric.pk).update(
                    requests=F("requests") + 1,
                    estimated=F("estimated") + int(event.estimated),
                    successes=F("successes") + int(event.response_status == 302),
                    updated_at=timezone.now(),
                )
                event.processed = True
                event.save(update_fields=["processed"])
                count += 1
        state, _ = WorkerState.objects.get_or_create(name="集計")
        WorkerState.objects.filter(pk=state.pk).update(
            last_run=timezone.now(), processed_total=F("processed_total") + count
        )
        self.stdout.write(f"{count}件を集計しました。")
