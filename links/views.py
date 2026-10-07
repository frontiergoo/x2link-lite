import hashlib
import io
import json
import secrets
import uuid
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit
import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction, DatabaseError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from .security import recent_auth, verify_mfa, locked, failed
from .forms import (
    WorkspaceForm,
    ReauthForm,
    SimulationForm,
    BulkForm,
    CampaignForm,
    LinkForm,
    LoginForm,
    TokenForm,
)
from .models import (
    Alias,
    Audit,
    Campaign,
    ClickEvent,
    ConversionJob,
    DailyMetric,
    Link,
    Membership,
    Revision,
    Workspace,
)
from .services import (
    Conflict,
    delete_link,
    set_blocked,
    create_link,
    device_type,
    estimated_click,
    extract_urls,
    resolve,
    restore_link,
    update_link,
)


def managed(edit=False):
    def decorate(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            membership = (
                Membership.objects.filter(user=request.user)
                .select_related("workspace")
                .first()
            )
            if not membership:
                return render(
                    request,
                    "links/status.html",
                    {"message": "このアカウントには管理権限がありません。"},
                    status=403,
                )
            if not request.user.is_verified():
                return redirect("mfa_setup")
            if edit and membership.role not in ("owner", "editor"):
                return render(
                    request,
                    "links/status.html",
                    {"message": "この操作には編集権限が必要です。"},
                    status=403,
                )
            request.membership = membership
            request.workspace = membership.workspace
            return fn(request, *args, **kwargs)

        return wrapper

    return decorate


def login_view(request):
    if request.user.is_authenticated and request.user.is_verified():
        return redirect("dashboard")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # ログイン失敗はアカウント単位でDBに記録し、複数プロセスでも共有する。
        from .models import LoginAttempt

        key = hashlib.sha256(
            form.cleaned_data["username"].casefold().encode()
        ).hexdigest()
        attempt, _ = LoginAttempt.objects.get_or_create(key=key)
        if attempt.locked_until and attempt.locked_until > timezone.now():
            form.add_error(
                None, "試行回数の上限に達しました。15分後に再試行してください。"
            )
        else:
            user = authenticate(
                request,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
            device = None
            if user:
                with transaction.atomic():
                    for candidate in TOTPDevice.objects.select_for_update().filter(
                        user=user, confirmed=True
                    ):
                        if candidate.verify_token(form.cleaned_data["token"]):
                            device = candidate
                            break
                    if not device:
                        for (
                            candidate
                        ) in StaticDevice.objects.select_for_update().filter(
                            user=user, confirmed=True
                        ):
                            if candidate.verify_token(form.cleaned_data["token"]):
                                device = candidate
                                break
                enrolled = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
                if device or not enrolled:
                    login(request, user)
                    if device:
                        otp_login(request, device)
                        request.session["verified_at"] = timezone.now().timestamp()
                    attempt.failures = 0
                    attempt.locked_until = None
                    attempt.save()
                    return redirect("dashboard" if device else "mfa_setup")
            from django.db.models import F

            LoginAttempt.objects.filter(pk=attempt.pk).update(
                failures=F("failures") + 1
            )
            attempt.refresh_from_db()
            if attempt.failures >= 5:
                attempt.locked_until = timezone.now() + timedelta(minutes=15)
                attempt.failures = 0
                attempt.save()
            form.add_error(
                None, "ユーザー名・パスワード・認証コードを確認してください。"
            )
    return render(request, "links/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


def mfa_setup(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if TOTPDevice.objects.filter(user=request.user, confirmed=True).exists():
        return redirect("login")
    device, _ = TOTPDevice.objects.get_or_create(
        user=request.user, confirmed=False, defaults={"name": "認証アプリ"}
    )
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            device = TOTPDevice.objects.select_for_update().get(pk=device.pk)
            if device.verify_token(form.cleaned_data["token"]):
                device.confirmed = True
                device.save()
                backup = StaticDevice.objects.create(
                    user=request.user, name="回復コード"
                )
                codes = [secrets.token_hex(8) for _ in range(10)]
                for code in codes:
                    StaticToken.objects.create(device=backup, token=code)
                otp_login(request, device)
                request.session["verified_at"] = timezone.now().timestamp()
                return render(request, "links/recovery.html", {"codes": codes})
        form.add_error("token", "認証コードを確認してください。")
    return render(
        request, "links/mfa.html", {"form": form, "config_url": device.config_url}
    )


def mfa_qr(request):
    if (
        not request.user.is_authenticated
        or TOTPDevice.objects.filter(user=request.user, confirmed=True).exists()
    ):
        return HttpResponse(status=404)
    device = get_object_or_404(TOTPDevice, user=request.user, confirmed=False)
    image = qrcode.make(device.config_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")


@managed()
def dashboard(request):
    links = (
        Link.objects.filter(workspace=request.workspace)
        .select_related("campaign")
        .prefetch_related("aliases")
        .order_by("-created_at")
    )
    q = request.GET.get("q", "")
    if q:
        links = links.filter(
            Q(name__icontains=q)
            | Q(destination__icontains=q)
            | Q(note__icontains=q)
            | Q(campaign__name__icontains=q)
        )
    state = request.GET.get("state", "")
    if state in dict(Link.STATES):
        links = links.filter(state=state)
    tag = request.GET.get("tag", "")
    from django.db import connection
    from django.core.paginator import Paginator

    if tag and connection.vendor == "postgresql":
        links = links.filter(tags__contains=[tag])
    elif tag:
        links = [link for link in links if tag in link.tags]
    page = Paginator(links, 50).get_page(request.GET.get("page"))
    filters = request.GET.copy()
    filters.pop("page", None)
    return render(
        request,
        "links/dashboard.html",
        {
            "links": page,
            "page": page,
            "filter_query": filters.urlencode(),
            "states": Link.STATES,
            "q": q,
            "state": state,
            "tag": tag,
            "origin": settings.PUBLIC_ORIGIN,
            "workspace": request.workspace,
        },
    )


@managed(edit=True)
def link_create(request):
    form = LinkForm(request.POST or None, workspace=request.workspace)
    if request.method == "POST" and form.is_valid():
        if (
            Link.objects.filter(
                workspace=request.workspace,
                created_at__gte=timezone.now() - timedelta(hours=1),
            ).count()
            >= 100
        ):
            form.add_error(None, "1時間に作成できるリンクは100件までです。")
        else:
            try:
                link = create_link(
                    request.workspace,
                    request.user,
                    form.cleaned_data,
                    form.cleaned_data.get("slug"),
                )
                messages.success(request, "リンクを作成しました。")
                return redirect("link_detail", pk=link.pk)
            except IntegrityError:
                form.add_error(
                    None, "このスラッグは使用済みです。別の文字列を指定してください。"
                )
            except ValidationError as e:
                form.add_error(None, e)
    return render(request, "links/form.html", {"form": form, "title": "リンクを作成"})


@managed()
def link_detail(request, pk):
    link = get_object_or_404(Link, pk=pk, workspace=request.workspace)
    from .analytics import report

    simulation = SimulationForm(request.GET or None)
    decision = resolve(link)
    if simulation.is_bound and simulation.is_valid():
        import copy

        simulated = copy.copy(link)
        if simulation.cleaned_data["as_published"]:
            simulated.state = "published"
        decision = resolve(
            simulated, simulation.cleaned_data["device"], simulation.cleaned_data["at"]
        )
    context = {
        "link": link,
        "origin": settings.PUBLIC_ORIGIN,
        "revisions": link.revisions.order_by("-version"),
        "decision": decision,
        "simulation": simulation,
        "audits": Audit.objects.filter(link=link)
        .select_related("actor")
        .order_by("-created_at")[:100],
    }
    context.update(report(request, Link.objects.filter(pk=link.pk)))
    return render(request, "links/detail.html", context)


@managed(edit=True)
def link_edit(request, pk):
    link = get_object_or_404(Link, pk=pk, workspace=request.workspace)
    form = LinkForm(request.POST or None, instance=link, workspace=request.workspace)
    if (
        request.method == "POST"
        and timezone.now().timestamp() - request.session.get("verified_at", 0) > 600
    ):
        request.session["reauth_return"] = request.path
        return redirect("reauth")
    if request.method == "POST" and form.is_valid():
        from .services import snapshot
        from .review import changes

        before = snapshot(Link.objects.get(pk=pk, workspace=request.workspace))
        after = snapshot(form.instance)
        preview_changes = changes(before, after)
        if request.POST.get("confirm") != "yes" and preview_changes:
            return render(
                request,
                "links/form.html",
                {
                    "form": form,
                    "title": "変更内容を確認",
                    "link": link,
                    "preview_changes": preview_changes,
                },
            )
        try:
            update_link(
                pk,
                request.workspace,
                request.user,
                form.cleaned_data,
                form.cleaned_data["expected_version"],
            )
            messages.success(request, "設定を更新しました。公開URLは変わりません。")
            return redirect("link_detail", pk=pk)
        except (Conflict, ValidationError) as e:
            form.add_error(None, str(e))
    return render(
        request,
        "links/form.html",
        {"form": form, "title": "リンクを編集", "link": link},
    )


@managed(edit=True)
@require_POST
@recent_auth
def link_action(request, pk):
    link = get_object_or_404(Link, pk=pk, workspace=request.workspace)
    action = request.POST.get("action")
    if link.deleted_at:
        messages.error(request, "削除済みリンクは変更できません。")
        return redirect("link_detail", pk=pk)
    try:
        version = int(request.POST.get("version", "0"))
        if action in ("block", "unblock"):
            if request.membership.role != "owner":
                return HttpResponse("この操作には管理者権限が必要です。", status=403)
            if (
                action == "unblock"
                and request.POST.get("unblock_confirm") != "安全性を確認しました"
            ):
                return HttpResponse(
                    "安全性を確認してから解除してください。", status=400
                )
            set_blocked(pk, request.workspace, request.user, version, action == "block")
            messages.success(
                request,
                "不正利用による停止を反映しました。"
                if action == "block"
                else "不正利用による停止を解除しました。",
            )
            return redirect("link_detail", pk=pk)
        if action == "delete":
            if (
                request.membership.role != "owner"
                or request.POST.get("delete_confirm") != "削除"
            ):
                return HttpResponse(
                    "管理者が確認欄に「削除」と入力してください。", status=403
                )
            delete_link(pk, request.workspace, request.user, version)
            messages.success(
                request, "内容と解析を削除しました。公開URLは予約状態で保持します。"
            )
            return redirect("link_detail", pk=pk)
        if action == "duplicate":
            from .services import snapshot

            values = snapshot(link)
            values.update(
                state="draft",
                name=link.name + "（複製）",
                starts_at=link.starts_at,
                ends_at=link.ends_at,
            )
            duplicate = create_link(request.workspace, request.user, values)
            return redirect("link_detail", pk=duplicate.pk)
        if action == "restore":
            revision = get_object_or_404(
                Revision, pk=request.POST.get("revision"), link=link
            )
            restore_link(link, request.user, revision, version)
        elif action in dict(Link.STATES):
            update_link(
                pk,
                request.workspace,
                request.user,
                {"state": action},
                version,
                "公開状態変更",
            )
        else:
            return HttpResponse("操作を確認してください。", status=400)
        messages.success(request, "変更を反映しました。")
    except (Conflict, ValidationError, ValueError) as e:
        message = (
            " ".join(e.messages)
            if isinstance(e, ValidationError)
            else str(e)
            if isinstance(e, Conflict)
            else "入力内容を確認してください。"
        )
        messages.error(request, message)
    return redirect("link_detail", pk=pk)


@managed()
def qr_download(request, pk, kind):
    link = get_object_or_404(Link, pk=pk, workspace=request.workspace)
    alias = link.aliases.first()
    value = settings.PUBLIC_ORIGIN + "/" + alias.path
    buffer = io.BytesIO()
    if kind == "svg":
        qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage, border=4).save(
            buffer
        )
        content_type = "image/svg+xml"
    elif kind == "png":
        qrcode.make(value, border=4).save(buffer, format="PNG")
        content_type = "image/png"
    else:
        return HttpResponse(status=404)
    response = HttpResponse(buffer.getvalue(), content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="x2link-{link.pk}.{kind}"'
    return response


@managed(edit=True)
def campaigns(request):
    form = CampaignForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        campaign = form.save(commit=False)
        campaign.workspace = request.workspace
        campaign.save()
        messages.success(request, "キャンペーンを作成しました。")
        return redirect("campaigns")
    return render(
        request,
        "links/campaigns.html",
        {
            "form": form,
            "campaigns": Campaign.objects.filter(workspace=request.workspace),
        },
    )


@require_http_methods(["GET", "HEAD"])
def public_redirect(request, path):
    try:
        alias = (
            Alias.objects.select_related("link__workspace")
            .filter(host=request.get_host().split(":")[0].lower(), path=path)
            .first()
        )
        if not alias:
            return render(
                request,
                "links/status.html",
                {"message": "このリンクは見つかりません。"},
                status=404,
            )
        agent = request.headers.get("User-Agent", "")[:512]
        decision = resolve(alias.link, device_type(agent))
        # 計測失敗で転送を失敗させない。秘密・IP・完全な参照元は保存しない。
        try:
            referrer = urlsplit(request.headers.get("Referer", "")).hostname or ""
            ClickEvent.objects.create(
                link=alias.link,
                device=device_type(agent),
                referrer=referrer[:253],
                response_status=decision.status,
                rule_version=1,
                estimated=decision.status == 302
                and estimated_click(request.method, agent),
            )
        except (DatabaseError, ValueError):
            import logging

            logging.getLogger("x2link").error(
                "クリックイベントの保存に失敗しました。計測欠損を監視してください。"
            )
        if decision.destination:
            response = HttpResponse(status=302)
            from django.utils.encoding import iri_to_uri

            response["Location"] = iri_to_uri(decision.destination)
            return response
        return render(
            request,
            "links/status.html",
            {"message": decision.message},
            status=decision.status,
        )
    except DatabaseError:
        return render(
            request,
            "links/status.html",
            {
                "message": "現在、安全な転送設定を確認できません。時間をおいて再度お試しください。"
            },
            status=503,
        )


@managed(edit=True)
def bulk_convert(request):
    form = BulkForm(request.POST or None, workspace=request.workspace)
    context = {
        "form": form,
        "job_key": request.POST.get("job_key") or str(uuid.uuid4()),
        "jobs": ConversionJob.objects.filter(workspace=request.workspace).order_by(
            "-created_at"
        )[:20],
    }
    if request.method == "POST" and form.is_valid():
        try:
            text = form.cleaned_data["text"]
            candidates = extract_urls(text)
            context["candidates"] = candidates
            context["preview"] = True
            if request.POST.get("confirm") == "yes":
                selected = {int(v) for v in request.POST.getlist("selected")}
                if not selected:
                    raise ValidationError("変換対象のURLを1件以上選択してください。")
                if any(
                    i < 0 or i >= len(candidates) or candidates[i]["error"]
                    for i in selected
                ):
                    raise ValidationError("変換対象のURLを確認してください。")
                fingerprint = hashlib.sha256(
                    json.dumps(
                        [
                            text,
                            sorted(selected),
                            form.cleaned_data["mode"],
                            str(
                                form.cleaned_data["campaign"].pk
                                if form.cleaned_data["campaign"]
                                else ""
                            ),
                            form.cleaned_data["keep_text"],
                        ],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                key = uuid.UUID(context["job_key"])
                with transaction.atomic():
                    job, created = (
                        ConversionJob.objects.select_for_update().get_or_create(
                            workspace=request.workspace,
                            key=key,
                            defaults={"fingerprint": fingerprint},
                        )
                    )
                    if not created and job.fingerprint != fingerprint:
                        raise ValidationError(
                            "再試行の内容が異なります。本文を再確認してください。"
                        )
                    if created:
                        count = Link.objects.filter(
                            workspace=request.workspace,
                            created_at__gte=timezone.now() - timedelta(hours=1),
                        ).count()
                        if count + len(selected) > 100:
                            raise ValidationError(
                                "1時間のリンク作成上限（100件）を超えます。"
                            )
                        generated = {}
                        replacements = []
                        for i in sorted(selected):
                            item = candidates[i]
                            group = (
                                item["url"]
                                if form.cleaned_data["mode"] == "shared"
                                else str(i)
                            )
                            if group not in generated:
                                link = create_link(
                                    request.workspace,
                                    request.user,
                                    {
                                        "destination": item["url"],
                                        "name": f"本文のリンク {i + 1}",
                                        "campaign": form.cleaned_data["campaign"],
                                        "placement": f"掲載位置 {i + 1}",
                                        "state": "draft",
                                    },
                                )
                                generated[group] = (
                                    settings.PUBLIC_ORIGIN
                                    + "/"
                                    + link.aliases.first().path
                                )
                            replacements.append(
                                {
                                    "start": item["start"],
                                    "end": item["end"],
                                    "url": generated[group],
                                    "original": item["url"],
                                }
                            )
                        output = text
                        for item in reversed(replacements):
                            output = (
                                output[: item["start"]]
                                + item["url"]
                                + output[item["end"] :]
                            )
                        job.result = {"replacements": replacements}
                        if form.cleaned_data["keep_text"]:
                            job.result["text"] = output
                        job.save()
                    output = text
                    for item in reversed(job.result.get("replacements", [])):
                        output = (
                            output[: item["start"]]
                            + item["url"]
                            + output[item["end"] :]
                        )
                    context["result"] = {**job.result, "text": output}
                    context["preview"] = False
                    context["job"] = job
        except ValidationError as e:
            form.add_error(None, e)
        except (ValueError, IntegrityError):
            form.add_error(
                None,
                "入力内容を確認してください。競合した場合は時間をおいて再試行してください。",
            )
    return render(request, "links/bulk.html", context)


@managed(edit=True)
@require_POST
@recent_auth
def bulk_publish(request, pk):
    job = get_object_or_404(ConversionJob, pk=pk, workspace=request.workspace)
    try:
        with transaction.atomic():
            aliases = Q(pk__in=[])
            for item in job.result.get("replacements", []):
                parsed = urlsplit(item["url"])
                aliases |= Q(host=parsed.hostname, path=parsed.path.lstrip("/"))
            ids = Alias.objects.filter(
                aliases, link__workspace=request.workspace
            ).values_list("link_id", flat=True)
            links = list(
                Link.objects.select_for_update().filter(pk__in=ids).order_by("pk")
            )
            expected = len({item["url"] for item in job.result.get("replacements", [])})
            if len(links) != expected:
                raise ValidationError(
                    "生成したリンクの対応を確認できません。公開せず、一覧と変換結果を確認してください。"
                )
            published = 0
            for link in links:
                if link.state != "draft":
                    continue
                if link.blocked or link.deleted_at:
                    raise ValidationError(
                        "停止・削除されたリンクが含まれています。一括公開は行いませんでした。"
                    )
                update_link(
                    link.pk,
                    request.workspace,
                    request.user,
                    {"state": "published"},
                    link.version,
                    "本文リンクの一括公開",
                )
                published += 1
        if published:
            messages.success(
                request,
                f"下書きリンク{published}件を公開しました。下書き以外の状態は変更していません。",
            )
        else:
            messages.info(
                request,
                "公開対象の下書きはありません。現在の公開・停止状態を確認してください。",
            )
        return redirect("dashboard")
    except (ValidationError, Conflict) as error:
        message = (
            " ".join(error.messages)
            if isinstance(error, ValidationError)
            else str(error)
        )
        messages.error(request, "一括公開は行いませんでした。" + message)
    except DatabaseError:
        messages.error(
            request,
            "一括公開を完了できませんでした。状態を確認し、時間をおいて再試行してください。",
        )
    return redirect("bulk_result", pk=job.pk)


@managed()
def export_data(request):
    from django.core.serializers import serialize

    querysets = [
        Workspace.objects.filter(pk=request.workspace.pk),
        Link.objects.filter(workspace=request.workspace),
        Alias.objects.filter(link__workspace=request.workspace),
        Revision.objects.filter(link__workspace=request.workspace),
        Campaign.objects.filter(workspace=request.workspace),
        DailyMetric.objects.filter(link__workspace=request.workspace),
    ]
    data = {
        "format": "x2link-export-v1",
        "exported_at": timezone.now().isoformat(),
        "records": [
            record for qs in querysets for record in json.loads(serialize("json", qs))
        ],
    }
    response = JsonResponse(
        data, json_dumps_params={"ensure_ascii": False, "indent": 2}
    )
    response["Content-Disposition"] = 'attachment; filename="x2link-export.json"'
    return response


@managed(edit=True)
@require_POST
@recent_auth
def emergency_stop(request):
    if request.membership.role != "owner":
        return HttpResponse("この操作には管理者権限が必要です。", status=403)
    stop = request.POST.get("stop") == "yes"
    request.workspace.emergency_stop = stop
    request.workspace.save(update_fields=["emergency_stop"])
    Audit.objects.create(
        workspace=request.workspace,
        actor=request.user,
        action="全リンク緊急停止" if stop else "緊急停止解除",
    )
    messages.success(
        request, "全リンクを停止しました。" if stop else "緊急停止を解除しました。"
    )
    return redirect("dashboard")


@managed()
def campaign_detail(request, pk):
    from .analytics import report

    campaign = get_object_or_404(Campaign, pk=pk, workspace=request.workspace)
    links = Link.objects.filter(campaign=campaign, workspace=request.workspace)
    context = {"campaign": campaign, "links": links}
    context.update(report(request, links))
    return render(request, "links/campaign_detail.html", context)


@managed()
def reauthenticate(request):
    form = ReauthForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if locked(request.user.username):
            form.add_error(
                None, "試行回数の上限に達しました。15分後に再試行してください。"
            )
        else:
            device = (
                verify_mfa(request.user, form.cleaned_data["token"])
                if request.user.check_password(form.cleaned_data["password"])
                else None
            )
            if device:
                otp_login(request, device)
                request.session["verified_at"] = timezone.now().timestamp()
                target = request.session.pop("reauth_return", "/manage/")
                # POSTを自動再送しない。確認画面に戻り、操作を再実行する。
                if target.endswith("/action/"):
                    target = target.removesuffix("action/")
                elif target.endswith("/publish/"):
                    target = target.removesuffix("publish/")
                elif target.endswith("/emergency/"):
                    target = "/manage/"
                messages.success(
                    request, "再認証しました。内容を確認して操作を実行してください。"
                )
                return redirect(target if target.startswith("/manage/") else "/manage/")
            failed(request.user.username)
            form.add_error(None, "パスワード・認証コードを確認してください。")
    return render(request, "links/reauth.html", {"form": form})


@require_http_methods(["GET", "HEAD"])
def readiness(request):
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM links_alias LIMIT 1")
        return JsonResponse({"状態": "稼働中"})
    except DatabaseError:
        return JsonResponse({"状態": "利用できません"}, status=503)


@managed()
def operations(request):
    from .models import WorkerState

    pending = ClickEvent.objects.filter(
        link__workspace=request.workspace, processed=False
    )
    oldest = pending.order_by("created_at").values_list("created_at", flat=True).first()
    state = WorkerState.objects.filter(name="集計").first()
    delayed = (
        not state
        or not state.last_run
        or state.last_run < timezone.now() - timedelta(minutes=5)
    )
    return render(
        request,
        "links/operations.html",
        {
            "pending": pending.count(),
            "oldest": oldest,
            "worker": state,
            "delayed": delayed,
        },
    )


@managed()
def bulk_result(request, pk):
    job = get_object_or_404(ConversionJob, pk=pk, workspace=request.workspace)
    return render(request, "links/bulk_result.html", {"job": job, "result": job.result})


@managed(edit=True)
def workspace_settings(request):
    if request.membership.role != "owner":
        return HttpResponse("この操作には管理者権限が必要です。", status=403)
    form = WorkspaceForm(request.POST or None, instance=request.workspace)
    if request.method == "POST":
        if timezone.now().timestamp() - request.session.get("verified_at", 0) > 600:
            request.session["reauth_return"] = request.path
            return redirect("reauth")
        if form.is_valid():
            form.save()
            Audit.objects.create(
                workspace=request.workspace,
                actor=request.user,
                action="ワークスペース設定変更",
                changes=list(form.changed_data),
            )
            messages.success(request, "設定を更新しました。")
            return redirect("workspace_settings")
    return render(request, "links/workspace_form.html", {"form": form})


def csrf_failure(request, reason=""):
    return render(
        request,
        "links/status.html",
        {
            "message": "操作を確認できませんでした。画面を再読み込みして、もう一度お試しください。"
        },
        status=403,
    )


def usage_notice(request):
    return render(
        request, "links/usage.html", {"support_email": settings.SUPPORT_EMAIL}
    )
