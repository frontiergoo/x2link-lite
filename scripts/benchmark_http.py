"""localhost内のHTTP負荷と停止反映を測る。本番SLOの証明には使わない。"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from socketserver import ThreadingMixIn
import sys
from threading import Thread
import time
from urllib.request import build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.core.wsgi import get_wsgi_application


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


server = make_server(
    "localhost",
    0,
    get_wsgi_application(),
    server_class=ThreadedServer,
    handler_class=QuietHandler,
)
Thread(target=server.serve_forever, daemon=True).start()
url = f"http://localhost:{server.server_port}/benchmark-check"


def request(index=0):
    start = time.perf_counter()
    try:
        build_opener(NoRedirect).open(url, timeout=5)
    except HTTPError as response:
        return (
            response.code,
            (time.perf_counter() - start) * 1000,
            response.headers.get("Location"),
            float(response.headers.get("Server-Timing", "app;dur=0").split("=")[-1]),
        )
    raise AssertionError("転送応答がありません。")


try:
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(request, range(100)))
    assert all(
        status == 302 and destination == "https://example.com/benchmark"
        for status, _, destination, _ in responses
    )
    server_durations = sorted(duration for _, _, _, duration in responses)
    durations = sorted(duration for _, duration, _, _ in responses)
    from django.conf import settings
    from links.models import Workspace

    workspace = Workspace.objects.get()
    start = time.perf_counter()
    workspace.emergency_stop = True
    workspace.save(update_fields=["emergency_stop"])
    assert request()[0] == 410
    reflected = (time.perf_counter() - start) * 1000
    output = {
        "環境": "localhost、HTTP、同時5接続、"
        + settings.DATABASES["default"]["ENGINE"],
        "リクエスト数": 100,
        "誤転送数": 0,
        "サービス処理p95_ms": round(server_durations[94], 2),
        "HTTP応答p95_ms": round(durations[94], 2),
        "停止の書込からHTTP反映まで_ms": round(reflected, 2),
        "本番SLO検証": False,
    }
    print(json.dumps(output, ensure_ascii=False))
finally:
    server.shutdown()
    server.server_close()
