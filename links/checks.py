from urllib.parse import urlsplit
from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def deployment_checks(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    errors = []
    origin = urlsplit(settings.PUBLIC_ORIGIN)
    if not settings.ADMIN_HOST or settings.ADMIN_HOST == settings.PUBLIC_HOST:
        errors.append(
            Error(
                "本番では管理ホストと公開転送ホストを分離してください。",
                id="x2link.E001",
            )
        )
    if (
        origin.scheme != "https"
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        errors.append(
            Error(
                "本番の公開URLはパス・クエリのないHTTPSのオリジンを指定してください。",
                id="x2link.E002",
            )
        )
    if not settings.SUPPORT_EMAIL:
        errors.append(
            Error(
                "公開前に問い合わせ先のメールアドレスを設定してください。",
                id="x2link.E004",
            )
        )
    return errors
