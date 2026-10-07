"""使い捨てDBでバックアップ・復元・HTTP転送を確認する。"""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def command(args, environment):
    result = subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def main():
    with tempfile.TemporaryDirectory(prefix="x2link-recovery-") as temporary:
        folder = Path(temporary)
        source, backup, restored = [
            folder / name
            for name in ("source.sqlite3", "backup.sqlite3", "restored.sqlite3")
        ]
        environment = dict(os.environ, X2LINK_DB_PATH=str(source), X2LINK_DEBUG="1")
        command(["migrate", "--noinput"], environment)
        command(
            [
                "shell",
                "-c",
                "from links.models import Workspace; from links.services import create_link; from django.contrib.auth import get_user_model; u=get_user_model().objects.create_user('復旧検証'); w=Workspace.objects.create(name='復旧検証'); create_link(w,u,{'destination':'https://example.com/recovery','state':'published'},'recovery-check')",
            ],
            environment,
        )
        command(["backup_database", str(backup)], environment)
        command(
            ["restore_database", str(backup), "--output", str(restored)], environment
        )
        with sqlite3.connect(source) as original, sqlite3.connect(restored) as recovery:
            for table in (
                "links_workspace",
                "links_link",
                "links_alias",
                "links_revision",
                "links_audit",
            ):
                assert (
                    original.execute(f"SELECT * FROM {table}").fetchall()
                    == recovery.execute(f"SELECT * FROM {table}").fetchall()
                ), table
        environment["X2LINK_DB_PATH"] = str(restored)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/verify_restored_http.py")],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        print(result.stdout.strip())
        print("バックアップ・復元・全設定の照合・HTTP転送検証に成功しました。")


if __name__ == "__main__":
    main()
