import sqlite3
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "SQLiteデータベースを整合性のあるバックアップに保存します。"

    def add_arguments(self, parser):
        parser.add_argument("output")

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        if db["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("このコマンドはSQLiteデータベース専用です。")
        path = Path(options["output"]).resolve()
        if path.exists():
            raise CommandError("既存のバックアップには上書きできません。")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db["NAME"]) as source, sqlite3.connect(path) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CommandError("バックアップの整合性検査に失敗しました。")
        path.chmod(0o600)
        self.stdout.write("バックアップを保存し、整合性を確認しました。")
