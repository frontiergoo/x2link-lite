import signal
import time
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connections
from django.utils import timezone


class Command(BaseCommand):
    help = "集計を毎分、保持期限処理を毎日実行します。"

    def handle(self, *args, **options):
        stopped = False

        def stop(*args):
            nonlocal stopped
            stopped = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        last_cleanup = None
        while not stopped:
            try:
                call_command("aggregate_clicks")
                if last_cleanup != timezone.localdate():
                    call_command("expire_data")
                    call_command("clearsessions")
                    last_cleanup = timezone.localdate()
            except Exception:
                self.stderr.write(
                    "集計処理に失敗しました。接続と監視ログを確認してください。"
                )
                connections.close_all()
            for _ in range(60):
                if stopped:
                    break
                time.sleep(1)
