"""使い捨て環境で転送のHTTP応答・反映時間を検査する。"""

import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix="x2link-performance-") as temporary:
    environment = dict(
        os.environ,
        X2LINK_DB_PATH=str(Path(temporary) / "benchmark.sqlite3"),
        X2LINK_DEBUG="1",
    )
    environment.pop("DATABASE_URL", None)
    subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
    )
    code = "from links.models import Workspace; from links.services import create_link; from django.contrib.auth import get_user_model; u=get_user_model().objects.create_user('負荷検証'); w=Workspace.objects.create(name='負荷検証'); create_link(w,u,{'destination':'https://example.com/benchmark','state':'published'},'benchmark-check')"
    subprocess.run(
        [sys.executable, "manage.py", "shell", "-c", code],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/benchmark_http.py")],
        cwd=ROOT,
        env=environment,
        check=True,
    )
