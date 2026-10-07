"""復元されたDBから実際のHTTP転送を検査する。"""

import os
import sys
from pathlib import Path
from threading import Thread
from urllib.request import build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from wsgiref.simple_server import make_server, WSGIRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.core.wsgi import get_wsgi_application


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


server = make_server("localhost", 0, get_wsgi_application(), handler_class=QuietHandler)
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    try:
        build_opener(NoRedirect).open(
            f"http://localhost:{server.server_port}/recovery-check", timeout=5
        )
    except HTTPError as response:
        assert response.code == 302, response.code
        assert response.headers["Location"] == "https://example.com/recovery"
        assert "no-store" in response.headers["Cache-Control"]
    else:
        raise AssertionError("302転送が返されませんでした。")
    print("復元DBの公開URLが正しい転送先へ302応答を返しました。")
finally:
    server.shutdown()
    server.server_close()
