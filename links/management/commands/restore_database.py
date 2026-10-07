import sqlite3
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "SQLiteバックアップを別ファイルに復元し検査します。稼働中DBの上書きは行いません。"

    def add_arguments(self, parser):
        parser.add_argument("backup")
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        source = Path(options["backup"]).resolve()
        target = Path(options["output"]).resolve()
        if not source.is_file() or target.exists():
            raise CommandError(
                "バックアップを確認し、存在しない復元先を指定してください。"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original:
                if original.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise CommandError("バックアップが破損しています。")
                with sqlite3.connect(target) as restored:
                    original.backup(restored)
                    if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise CommandError("復元後の検査に失敗しました。")
                    count = restored.execute(
                        "SELECT COUNT(*) FROM links_alias"
                    ).fetchone()[0]
        except sqlite3.Error as e:
            raise CommandError("データベースの復元に失敗しました。") from e
        target.chmod(0o600)
        self.stdout.write(
            f"復元と整合性検査が完了しました。公開別名：{count}件。切替前に転送の外形検証を行ってください。"
        )
