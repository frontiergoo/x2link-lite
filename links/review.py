from urllib.parse import urlsplit, urlunsplit
from .services import EDITABLE

LABELS = {
    "name": "名前",
    "destination": "転送先",
    "mobile_destination": "スマートフォンの転送先",
    "outside_destination": "期間外の転送先",
    "state": "公開状態",
    "starts_at": "開始日時",
    "ends_at": "終了日時",
    "campaign_id": "キャンペーン",
    "tags": "タグ",
    "note": "メモ",
    "placement": "掲載位置",
    "blocked": "不正利用による停止",
}


def display(field, value):
    if value is None or value == "" or value == []:
        return "指定なし"
    if field.endswith("destination"):
        parts = urlsplit(value)
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                "…" if parts.query else "",
                "…" if parts.fragment else "",
            )
        )
    if field == "state":
        from .models import Link

        return dict(Link.STATES).get(value, str(value))
    if field in ("starts_at", "ends_at"):
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        return timezone.localtime(parse_datetime(value)).strftime(
            "%Y/%m/%d %H:%M:%S（日本時間）"
        )
    if field == "campaign_id":
        from .models import Campaign

        campaign = Campaign.objects.filter(pk=value).first()
        return campaign.name if campaign else "削除済みのキャンペーン"
    if field == "note":
        return "内容あり（機密情報を表示しません）"
    return str(value)


def changes(before, after):
    return [
        {
            "label": LABELS[field],
            "before": display(field, before.get(field)),
            "after": display(field, after.get(field)),
        }
        for field in EDITABLE
        if before.get(field) != after.get(field)
    ]
