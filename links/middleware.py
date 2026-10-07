import time
from django.conf import settings


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response["Referrer-Policy"] = (
            "same-origin" if request.path.startswith("/manage/") else "no-referrer"
        )
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response["Cache-Control"] = "no-store, max-age=0"
        if settings.DEBUG:
            response["Server-Timing"] = (
                f"app;dur={(time.perf_counter() - started) * 1000:.2f}"
            )
        return response


class HostBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import HttpResponse
        from urllib.parse import urlsplit

        host = urlsplit("//" + request.get_host()).hostname
        management = request.path == "/manage" or request.path.startswith("/manage/")
        if settings.ADMIN_HOST and management and host != settings.ADMIN_HOST:
            return HttpResponse("このホストでは管理画面を利用できません。", status=404)
        return self.get_response(request)
