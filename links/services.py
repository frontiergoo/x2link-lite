import ipaddress
import re
import secrets
from dataclasses import dataclass
from datetime import timezone as utc_timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote_plus
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import Alias, Audit, Campaign, Link, Revision, Workspace

RESERVED = {
    "manage",
    "api",
    "static",
    "health",
    "favicon.ico",
    "robots.txt",
    ".well-known",
    "usage",
}
EDITABLE = [
    "name",
    "destination",
    "mobile_destination",
    "outside_destination",
    "state",
    "starts_at",
    "ends_at",
    "campaign_id",
    "tags",
    "note",
    "placement",
    "blocked",
]


class Conflict(Exception):
    pass


def validate_destination(value):
    if not value or len(value) > 4096 or re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValidationError("転送先URLに空白・制御文字・不正な文字が含まれています。")
    try:
        p = urlsplit(value)
        host = p.hostname
        _ = p.port
    except ValueError:
        raise ValidationError("転送先URLの形式を確認してください。")
    if (
        p.scheme not in ("http", "https")
        or not host
        or p.username is not None
        or p.password is not None
    ):
        raise ValidationError(
            "認証情報を含まないHTTPまたはHTTPSのURLを指定してください。"
        )
    host = host.lower().rstrip(".")
    if (
        "%" in host
        or host == settings.PUBLIC_HOST
        or host in ("localhost", "testserver")
        or host.endswith(
            (".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid")
        )
    ):
        raise ValidationError("内部向け・自己参照・予約済みホストは登録できません。")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise ValidationError("ホスト名の形式を確認してください。")
        if (
            "." not in ascii_host
            or not re.fullmatch(r"[a-z0-9.-]+", ascii_host)
            or all(part.isdigit() for part in ascii_host.split("."))
        ):
            raise ValidationError("公開ホスト名を指定してください。")
        if any(
            not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
            for part in ascii_host.split(".")
        ):
            raise ValidationError("ホスト名の形式を確認してください。")
    else:
        if not ip.is_global:
            raise ValidationError("内部向け・予約済みIPアドレスは登録できません。")
    return value


def validate_public_dns(url):
    import dns.exception
    import dns.resolver

    host = urlsplit(url).hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
        addresses = [address]
    except ValueError:
        addresses = []
        for record_type in ("A", "AAAA"):
            try:
                answer = dns.resolver.resolve(
                    host.encode("idna").decode(), record_type, lifetime=2
                )
                addresses.extend(ipaddress.ip_address(str(record)) for record in answer)
            except dns.resolver.NoAnswer:
                continue
            except dns.exception.DNSException:
                raise ValidationError(
                    "転送先の公開DNSを確認できません。ホスト名を確認して再試行してください。"
                )
        if not addresses:
            raise ValidationError("転送先の公開アドレスが見つかりません。")
    if any(not address.is_global for address in addresses):
        raise ValidationError(
            "内部向け・予約済みアドレスに解決される転送先は登録できません。"
        )
    # 登録時だけDNSを確認する。公開転送時には外部通信せず、P1の監視・取得は実装しない。
    return url


def validate_slug(slug):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}", slug) or slug in RESERVED:
        raise ValidationError(
            "スラッグは小文字英数字・ハイフン・下線の3〜64文字で指定してください。予約語は使えません。"
        )
    return slug


def generate_slug():
    return "".join(secrets.choice("23456789abcdefghjkmnpqrstuvwxyz") for _ in range(9))


def validate_link(link):
    for field in ("destination", "mobile_destination", "outside_destination"):
        value = getattr(link, field)
        if value:
            validate_destination(value)
            if Alias.objects.filter(
                host=urlsplit(value).hostname.lower().rstrip(".")
            ).exists():
                raise ValidationError("管理下の転送ドメインを転送先にはできません。")
            validate_public_dns(value)
    if link.starts_at and link.ends_at and link.ends_at <= link.starts_at:
        raise ValidationError("終了日時は開始日時より後にしてください。")
    if (
        link.campaign_id
        and not Campaign.objects.filter(
            pk=link.campaign_id, workspace=link.workspace
        ).exists()
    ):
        raise ValidationError("このワークスペースのキャンペーンを選択してください。")
    if (
        not isinstance(link.tags, list)
        or len(link.tags) > 20
        or any(not isinstance(t, str) or len(t) > 64 for t in link.tags)
    ):
        raise ValidationError("タグは各64文字以内、20件まで指定できます。")
    link.full_clean()


def snapshot(link):
    result = {}
    for field in EDITABLE:
        value = getattr(link, field)
        result[field] = (
            value.astimezone(utc_timezone.utc).isoformat()
            if field in ("starts_at", "ends_at") and value
            else value
        )
    return result


def record(link, actor, action, changes=None):
    Revision.objects.create(link=link, version=link.version, snapshot=snapshot(link))
    Audit.objects.create(
        workspace=link.workspace,
        actor=actor,
        link=link,
        action=action,
        version=link.version,
        changes=changes or [],
    )


@transaction.atomic
def create_link(workspace, actor, values, slug=None):
    Workspace.objects.select_for_update().get(pk=workspace.pk)
    values = dict(values)
    if "campaign" in values:
        values["campaign_id"] = values["campaign"].pk if values["campaign"] else None
    if values.get("tags") is None:
        values["tags"] = []
    from datetime import timedelta

    if (
        Link.objects.filter(
            workspace=workspace, created_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
        >= 100
    ):
        raise ValidationError("1時間に作成できるリンクは100件までです。")
    slug = validate_slug(slug) if slug else generate_slug()
    link = Link(
        workspace=workspace,
        **{k: v for k, v in values.items() if k in EDITABLE and k != "blocked"},
    )
    validate_link(link)
    link.save()
    Alias.objects.create(link=link, host=settings.PUBLIC_HOST, path=slug)
    record(link, actor, "作成")
    return link


@transaction.atomic
def update_link(link_id, workspace, actor, values, version, action="設定変更"):
    values = dict(values)
    if "campaign" in values:
        values["campaign_id"] = values["campaign"].pk if values["campaign"] else None
    if "tags" in values and values["tags"] is None:
        values["tags"] = []
    link = Link.objects.select_for_update().get(pk=link_id, workspace=workspace)
    if link.deleted_at:
        raise ValidationError(
            "削除済みリンクの設定は変更できません。公開別名は予約状態です。"
        )
    if link.version != version:
        raise Conflict("別の操作で更新されています。最新の内容を確認してください。")
    before = snapshot(link)
    for k, v in values.items():
        if k in EDITABLE and k != "blocked":
            setattr(link, k, v)
    safety_stop = set(values) == {"state"} and values["state"] in ("paused", "archived")
    if not safety_stop:
        validate_link(link)
    previous = link.version
    link.version += 1
    data = {f: getattr(link, f) for f in EDITABLE}
    data.update(version=link.version, updated_at=timezone.now())
    if Link.objects.filter(pk=link.pk, version=previous).update(**data) != 1:
        raise Conflict("別の操作で更新されています。最新の内容を確認してください。")
    after = snapshot(link)
    record(
        link,
        actor,
        action,
        [field for field in EDITABLE if before[field] != after[field]],
    )
    return link


def restore_link(link, actor, revision, version):
    if revision.link_id != link.pk:
        raise ValidationError("対象リンクの履歴を選択してください。")
    values = dict(revision.snapshot)
    for field in ("starts_at", "ends_at"):
        values[field] = parse_datetime(values[field]) if values[field] else None
    return update_link(link.pk, link.workspace, actor, values, version, "履歴から復元")


@dataclass(frozen=True)
class Decision:
    status: int
    destination: str = ""
    message: str = ""


def resolve(link, device="unknown", now=None):
    now = now or timezone.now()
    if link.deleted_at:
        return Decision(410, message="このリンクは削除されています。")
    if (
        link.blocked
        or link.workspace.emergency_stop
        or link.state in ("paused", "archived")
    ):
        return Decision(410, message="このリンクは停止されています。")
    if link.state != "published":
        return Decision(404, message="このリンクは公開されていません。")
    outside = (link.starts_at and now < link.starts_at) or (
        link.ends_at and now >= link.ends_at
    )
    if outside:
        destination = link.outside_destination or link.workspace.outside_destination
        if not destination:
            return Decision(410, message="このリンクは有効期間外です。")
    else:
        destination = (
            link.mobile_destination
            if device == "mobile" and link.mobile_destination
            else link.destination
        )
    try:
        validate_destination(destination)
    except ValidationError:
        return Decision(503, message="安全な転送先を確認できません。")
    return Decision(302, destination)


def device_type(user_agent):
    if not user_agent:
        return "unknown"
    return (
        "mobile" if re.search(r"Android|iPhone|Mobile", user_agent, re.I) else "desktop"
    )


def estimated_click(method, user_agent):
    return (
        method == "GET"
        and bool(user_agent)
        and not re.search(
            r"bot|crawler|spider|preview|scanner|safe.?links|headless", user_agent, re.I
        )
    )


def add_utm(url, source="", medium="", campaign="", overwrite=False):
    validate_destination(url)
    additions = {
        k: v
        for k, v in [
            ("utm_source", source),
            ("utm_medium", medium),
            ("utm_campaign", campaign),
        ]
        if v
    }
    if not additions:
        return url
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if any(
        re.search(r"(^|[-_])(signature|token|sig|credential|expires)($|[-_])", k, re.I)
        for k, v in pairs
    ):
        raise ValidationError("署名・認証情報を含むURLへのUTM追加はできません。")
    if any(
        len(v) > 200 or re.search(r"[\x00-\x1f\x7f]", v) for v in additions.values()
    ):
        raise ValidationError(
            "UTMの値は制御文字を含まない200文字以内で指定してください。"
        )
    if not overwrite and any(k in additions and v != additions[k] for k, v in pairs):
        raise ValidationError("既存のUTMを上書きするには確認が必要です。")
    # UTM以外のクエリは再エンコードせず、元の文字列・順序を維持する。
    kept = [
        part
        for part in parts.query.split("&")
        if part and unquote_plus(part.split("=", 1)[0]) not in additions
    ]
    query = "&".join(kept + [urlencode(additions)])
    result = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    validate_destination(result)
    return result


def extract_urls(text):
    if len(text) > 100000:
        raise ValidationError("本文は100,000文字以内にしてください。")
    result = []
    for match in re.finditer(r"https?://[^\s<>「」『』【】。、，．（）]+", text):
        url = match.group().rstrip("。、，．!！?？）]")
        while url.endswith(")") and url.count(")") > url.count("("):
            url = url[:-1]
        try:
            validate_destination(url)
            error = ""
        except ValidationError as e:
            error = " ".join(e.messages)
        result.append(
            {
                "start": match.start(),
                "end": match.start() + len(url),
                "url": url,
                "error": error,
            }
        )
    if len(result) > 100:
        raise ValidationError("本文内のURLは100件まで対応しています。")
    return result


@transaction.atomic
def delete_link(link_id, workspace, actor, version):
    from .models import ClickEvent, ConversionJob, DailyMetric

    link = Link.objects.select_for_update().get(pk=link_id, workspace=workspace)
    if link.deleted_at:
        return link
    if link.version != version:
        raise Conflict("別の操作で更新されています。最新の内容を確認してください。")
    # 公開別名と不変IDは予約用に残し、利用者のコンテンツ・解析を消去する。
    link.state = "archived"
    link.deleted_at = timezone.now()
    link.name = "削除済み"
    link.destination = "https://example.invalid/"
    link.mobile_destination = ""
    link.outside_destination = ""
    link.note = ""
    link.tags = []
    link.campaign = None
    link.placement = ""
    link.starts_at = None
    link.ends_at = None
    link.version += 1
    link.save()
    Revision.objects.filter(link=link).delete()
    ClickEvent.objects.filter(link=link).delete()
    DailyMetric.objects.filter(link=link).delete()
    Audit.objects.filter(link=link).delete()
    # 本文結果に削除対象の内容を残さない。本文の完全な位置索引は保持しないため全件消去する。
    ConversionJob.objects.filter(workspace=workspace).delete()
    Audit.objects.create(
        workspace=workspace, actor=actor, link=link, action="内容の完全削除・別名予約"
    )
    return link


@transaction.atomic
def set_blocked(link_id, workspace, actor, version, blocked):
    link = Link.objects.select_for_update().get(pk=link_id, workspace=workspace)
    if link.deleted_at or link.version != version:
        raise Conflict("削除済み、または別の操作で更新されています。")
    if not blocked:
        validate_link(link)
    link.blocked = blocked
    link.version += 1
    link.save(update_fields=["blocked", "version", "updated_at"])
    record(
        link,
        actor,
        "不正利用による停止" if blocked else "不正利用による停止の解除",
        ["blocked"],
    )
    return link
