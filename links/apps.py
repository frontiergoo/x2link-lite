from django.apps import AppConfig


class LinksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "links"
    verbose_name = "リンク運用"

    def ready(self):
        from . import checks  # noqa: F401 -- 公開設定検査を登録する。
