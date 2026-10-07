from datetime import timedelta
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, DatabaseError
from django.test import TestCase, Client
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from .models import (
    Alias,
    Campaign,
    ClickEvent,
    DailyMetric,
    Link,
    Membership,
    Workspace,
)
from .services import (
    Conflict,
    add_utm,
    create_link,
    extract_urls,
    resolve,
    restore_link,
    update_link,
    validate_destination,
)


class FixtureMixin:
    def setUp(self):
        from .services import validate_public_dns

        self.real_dns_validator = validate_public_dns
        dns_patch = patch("links.services.validate_public_dns")
        dns_patch.start()
        self.addCleanup(dns_patch.stop)
        self.user = get_user_model().objects.create_user(
            "管理者", password="secure-password-2026"
        )
        self.workspace = Workspace.objects.create(name="テスト")
        self.link = create_link(
            self.workspace,
            self.user,
            {
                "destination": "https://example.com/offer?x=1#detail",
                "state": "published",
            },
            "sample",
        )


class RulesTests(FixtureMixin, TestCase):
    def test_private_dns_is_rejected_without_fetching_destination(self):
        # 実装用のモックを止め、DNS応答だけを固定して公開アドレスの判定を検査する。
        import dns.resolver

        original = self.real_dns_validator
        with patch(
            "dns.resolver.resolve", side_effect=[["127.0.0.1"], dns.resolver.NoAnswer]
        ):
            with self.assertRaises(ValidationError):
                original("https://public-looking.example.com")
        with patch(
            "dns.resolver.resolve",
            side_effect=[["93.184.216.34"], dns.resolver.NoAnswer],
        ):
            self.assertEqual(original("https://example.com"), "https://example.com")

    def test_url_validation(self):
        invalid = [
            "javascript:alert(1)",
            "http://localhost/x",
            "http://127.0.0.1",
            "http://[::1]",
            "http://10.0.0.1",
            "https://name:secret@example.com",
            "https://example.com/\r\nX:abc",
            "http://2130706433",
            "http://127.1",
            "http://foo.internal",
            "https://localhost:8000/sample",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_destination(value)
        self.assertEqual(
            validate_destination(self.link.destination), self.link.destination
        )

    def test_state_and_boundaries(self):
        now = timezone.now()
        self.link.starts_at = now
        self.link.ends_at = now + timedelta(hours=1)
        self.assertEqual(
            resolve(self.link, now=now - timedelta(microseconds=1)).status, 410
        )
        self.assertEqual(resolve(self.link, now=now).status, 302)
        self.assertEqual(resolve(self.link, now=self.link.ends_at).status, 410)
        self.link.outside_destination = "https://example.org/expired"
        self.assertEqual(
            resolve(self.link, now=self.link.ends_at).destination,
            self.link.outside_destination,
        )
        self.link.state = "paused"
        self.assertEqual(resolve(self.link, now=self.link.ends_at).status, 410)
        self.link.state = "draft"
        self.assertEqual(resolve(self.link).status, 404)

    def test_device_fallback(self):
        self.link.mobile_destination = "https://example.org/mobile"
        self.assertEqual(
            resolve(self.link, "unknown").destination, self.link.destination
        )
        self.assertEqual(
            resolve(self.link, "mobile").destination, self.link.mobile_destination
        )

    def test_unique_alias_and_transaction(self):
        with self.assertRaises(IntegrityError):
            create_link(
                self.workspace,
                self.user,
                {"destination": "https://example.org"},
                "sample",
            )
        self.assertEqual(Link.objects.count(), 1)

    def test_version_conflict_restore_and_alias_retained(self):
        changed = update_link(
            self.link.pk,
            self.workspace,
            self.user,
            {"destination": "https://example.org/new"},
            1,
        )
        with self.assertRaises(Conflict):
            update_link(self.link.pk, self.workspace, self.user, {"state": "paused"}, 1)
        original = self.link.revisions.get(version=1)
        restored = restore_link(changed, self.user, original, 2)
        self.assertEqual(restored.destination, self.link.destination)
        self.assertEqual(restored.version, 3)
        self.assertEqual(Alias.objects.get(link=self.link).path, "sample")

    def test_campaign_ownership(self):
        other = Workspace.objects.create(name="別組織")
        campaign = Campaign.objects.create(workspace=other, name="別施策")
        with self.assertRaises(ValidationError):
            create_link(
                self.workspace,
                self.user,
                {"destination": "https://example.org", "campaign_id": campaign.pk},
            )

    def test_utm_collision_and_signed_url(self):
        with self.assertRaises(ValidationError):
            add_utm("https://example.com/?utm_source=old", source="new")
        self.assertIn(
            "utm_source=new",
            add_utm(
                "https://example.com/?utm_source=old", source="new", overwrite=True
            ),
        )
        with self.assertRaises(ValidationError):
            add_utm("https://example.com/?signature=secret", source="mail")

    def test_text_extraction_keeps_parameters_and_japanese_punctuation(self):
        text = (
            "ご案内：https://example.com/a?x=1#top。次は（https://example.org/a(b)）。"
        )
        results = extract_urls(text)
        self.assertEqual(
            [r["url"] for r in results],
            ["https://example.com/a?x=1#top", "https://example.org/a(b)"],
        )
        for result in results:
            self.assertEqual(text[result["start"] : result["end"]], result["url"])


class IntegrationTests(FixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        Membership.objects.create(user=self.user, workspace=self.workspace)
        device = TOTPDevice.objects.create(user=self.user, name="試験", confirmed=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["verified_at"] = timezone.now().timestamp()
        session["otp_device_id"] = device.persistent_id
        session.save()

    def test_public_redirect_no_cache_and_head_excluded(self):
        response = self.client.get(
            "/sample?next=https://evil.example",
            HTTP_HOST="localhost",
            HTTP_USER_AGENT="Mozilla/5.0",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.link.destination)
        self.assertIn("no-store", response["Cache-Control"])
        self.client.head(
            "/sample", HTTP_HOST="localhost", HTTP_USER_AGENT="Mozilla/5.0"
        )
        self.assertEqual(ClickEvent.objects.filter(estimated=True).count(), 1)

    def test_analytics_failure_does_not_break_redirect(self):
        with patch(
            "links.views.ClickEvent.objects.create",
            side_effect=DatabaseError("計測停止"),
        ):
            response = self.client.get("/sample", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 302)

    def test_host_isolation_and_unknown(self):
        self.assertEqual(
            self.client.get("/sample", HTTP_HOST="testserver").status_code, 404
        )
        self.assertEqual(
            self.client.get("/missing", HTTP_HOST="localhost").status_code, 404
        )

    def test_manage_pages_and_creation(self):
        for path in [
            "/manage/",
            "/manage/campaigns/",
            "/manage/bulk/",
            f"/manage/links/{self.link.pk}/",
            "/manage/links/new/",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.post(
            "/manage/links/new/",
            {
                "destination": "https://example.org/new",
                "state": "draft",
                "name": "新規",
                "tags": "[]",
                "slug": "new-link",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Alias.objects.filter(path="new-link").exists())

    def test_ownership_and_mfa_required(self):
        other = Workspace.objects.create(name="別組織")
        link = create_link(other, self.user, {"destination": "https://example.org"})
        self.assertEqual(self.client.get(f"/manage/links/{link.pk}/").status_code, 404)
        client = Client()
        self.assertEqual(client.get("/manage/").status_code, 302)
        client.force_login(self.user)
        self.assertEqual(client.get("/manage/").url, "/manage/mfa/")

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(
            client.post(
                "/manage/links/new/", {"destination": "https://example.org"}
            ).status_code,
            403,
        )

    def test_aggregation_idempotent(self):
        ClickEvent.objects.create(link=self.link, device="mobile", estimated=True)
        call_command("aggregate_clicks", verbosity=0)
        call_command("aggregate_clicks", verbosity=0)
        metric = DailyMetric.objects.get(link=self.link)
        self.assertEqual((metric.requests, metric.estimated), (1, 1))

    def test_qr_png_and_svg(self):
        for kind in ["png", "svg"]:
            response = self.client.get(f"/manage/links/{self.link.pk}/qr/{kind}/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response["Content-Disposition"])

    def test_export_does_not_include_auth_secrets(self):
        response = self.client.get("/manage/export/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.user.password, response.content.decode())
        self.assertNotIn("otp_totp", response.content.decode())

    def test_bulk_idempotent(self):
        import uuid

        data = {
            "text": "本文 https://example.org/a。",
            "mode": "position",
            "job_key": str(uuid.uuid4()),
            "selected": ["0"],
            "confirm": "yes",
        }
        before = Link.objects.count()
        self.assertEqual(self.client.post("/manage/bulk/", data).status_code, 200)
        self.assertEqual(self.client.post("/manage/bulk/", data).status_code, 200)
        self.assertEqual(Link.objects.count(), before + 1)

    def test_utm_creation_preserves_unrelated_query_bytes(self):
        response = self.client.post(
            "/manage/links/new/",
            {
                "destination": "https://example.org/?a=%2f%20&b=1+2#top",
                "state": "draft",
                "tags": "メール, 秋",
                "utm_source": "newsletter",
                "utm_medium": "email",
                "utm_campaign": "autumn",
            },
        )
        self.assertEqual(response.status_code, 302)
        link = Link.objects.exclude(pk=self.link.pk).get()
        self.assertIn("a=%2f%20&b=1+2", link.destination)
        self.assertEqual(link.tags, ["メール", "秋"])
        self.assertIn("utm_source=newsletter", link.destination)

    def test_simulation_is_not_counted(self):
        response = self.client.get(
            f"/manage/links/{self.link.pk}/",
            {"device": "mobile", "at": "2030-01-01T10:00"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HTTP 302")
        self.assertEqual(ClickEvent.objects.count(), 0)

    def test_campaign_report_filters_and_ownership(self):
        campaign = Campaign.objects.create(workspace=self.workspace, name="秋の施策")
        self.link.campaign = campaign
        self.link.save()
        DailyMetric.objects.create(
            link=self.link,
            date=timezone.localdate(),
            device="mobile",
            requests=10,
            estimated=7,
        )
        response = self.client.get(
            f"/manage/campaigns/{campaign.pk}/", {"device": "mobile"}
        )
        self.assertContains(response, "秋の施策")
        self.assertEqual(response.context["total"]["estimated"], 7)
        other = Campaign.objects.create(
            workspace=Workspace.objects.create(name="別"), name="別施策"
        )
        self.assertEqual(
            self.client.get(f"/manage/campaigns/{other.pk}/").status_code, 404
        )

    def test_pausing_requires_recent_auth_and_retains_alias(self):
        session = self.client.session
        session["verified_at"] = 0
        session.save()
        response = self.client.post(
            f"/manage/links/{self.link.pk}/action/", {"action": "paused", "version": 1}
        )
        self.assertEqual(response.url, "/manage/reauth/")
        self.link.refresh_from_db()
        self.assertEqual(self.link.state, "published")
        session = self.client.session
        session["verified_at"] = timezone.now().timestamp()
        session.save()
        self.client.post(
            f"/manage/links/{self.link.pk}/action/", {"action": "paused", "version": 1}
        )
        self.assertEqual(
            self.client.get("/sample", HTTP_HOST="localhost").status_code, 410
        )
        self.assertEqual(Alias.objects.get(link=self.link).path, "sample")

    def test_viewer_cannot_edit_or_stop(self):
        Membership.objects.filter(user=self.user).update(role="viewer")
        self.assertEqual(self.client.post("/manage/links/new/", {}).status_code, 403)
        self.assertEqual(
            self.client.post("/manage/emergency/", {"stop": "yes"}).status_code, 403
        )

    def test_logout_invalidates_session(self):
        self.client.post("/manage/logout/")
        self.assertEqual(self.client.get("/manage/").url, "/manage/login/")

    def test_qr_decodes_to_public_url(self):
        import io
        import zxingcpp
        from PIL import Image

        response = self.client.get(f"/manage/links/{self.link.pk}/qr/png/")
        result = zxingcpp.read_barcode(Image.open(io.BytesIO(response.content)))
        self.assertEqual(result.text, settings.PUBLIC_ORIGIN + "/sample")

    def test_event_retention_does_not_delete_revisions(self):
        old = timezone.now() - timedelta(days=200)
        processed = ClickEvent.objects.create(
            link=self.link, device="mobile", processed=True
        )
        pending = ClickEvent.objects.create(
            link=self.link, device="mobile", processed=False
        )
        ClickEvent.objects.filter(pk__in=[processed.pk, pending.pk]).update(
            created_at=old
        )
        call_command("expire_data", verbosity=0)
        self.assertFalse(ClickEvent.objects.filter(pk=processed.pk).exists())
        self.assertTrue(ClickEvent.objects.filter(pk=pending.pk).exists())
        self.assertEqual(self.link.revisions.count(), 1)

    def test_deleted_content_is_scrubbed_and_alias_cannot_be_reused(self):
        response = self.client.post(
            f"/manage/links/{self.link.pk}/action/",
            {"action": "delete", "version": 1, "delete_confirm": "削除"},
        )
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.assertIsNotNone(self.link.deleted_at)
        self.assertEqual(self.link.revisions.count(), 0)
        self.assertEqual(
            self.client.get("/sample", HTTP_HOST="localhost").status_code, 410
        )
        with self.assertRaises(ValidationError):
            update_link(
                self.link.pk,
                self.workspace,
                self.user,
                {"state": "published", "destination": "https://example.org/new"},
                2,
            )
        with self.assertRaises(IntegrityError):
            create_link(
                self.workspace,
                self.user,
                {"destination": "https://example.org"},
                "sample",
            )

    def test_body_is_not_saved_by_default_and_job_can_resume(self):
        import uuid
        from .models import ConversionJob

        text = "保存しない本文 https://example.org/a。"
        self.client.post(
            "/manage/bulk/",
            {
                "text": text,
                "mode": "position",
                "job_key": str(uuid.uuid4()),
                "selected": ["0"],
                "confirm": "yes",
            },
        )
        job = ConversionJob.objects.get()
        self.assertNotIn("text", job.result)
        self.assertEqual(self.client.get(f"/manage/bulk/{job.pk}/").status_code, 200)
        self.client.post(f"/manage/bulk/{job.pk}/publish/")
        link = Link.objects.exclude(pk=self.link.pk).get()
        self.assertEqual(link.state, "published")

    def test_edit_requires_difference_confirmation(self):
        data = {
            "destination": "https://example.org/changed",
            "state": "published",
            "tags": "",
            "expected_version": 1,
        }
        response = self.client.post(f"/manage/links/{self.link.pk}/edit/", data)
        self.assertContains(response, "変更前と変更後")
        self.link.refresh_from_db()
        self.assertEqual(self.link.version, 1)
        data["confirm"] = "yes"
        response = self.client.post(f"/manage/links/{self.link.pk}/edit/", data)
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.destination, "https://example.org/changed")
        self.assertIn("destination", self.link.audit_set.latest("created_at").changes)

    def test_request_and_success_counts_are_distinct(self):
        self.client.get("/sample", HTTP_HOST="localhost", HTTP_USER_AGENT="Mozilla/5.0")
        self.link.state = "paused"
        self.link.save()
        self.client.get("/sample", HTTP_HOST="localhost", HTTP_USER_AGENT="Mozilla/5.0")
        call_command("aggregate_clicks", verbosity=0)
        metric = DailyMetric.objects.get(link=self.link)
        self.assertEqual(
            (metric.requests, metric.successes, metric.estimated), (2, 1, 1)
        )
        self.assertEqual(
            set(ClickEvent.objects.values_list("rule_version", flat=True)), {1}
        )

    def test_global_expiry_target_and_draft_simulation(self):
        self.workspace.outside_destination = "https://example.org/global-expired"
        self.workspace.save()
        self.link.workspace = self.workspace
        self.link.ends_at = timezone.now() - timedelta(seconds=1)
        self.assertEqual(
            resolve(self.link).destination, self.workspace.outside_destination
        )
        self.link.state = "draft"
        self.link.save()
        response = self.client.get(
            f"/manage/links/{self.link.pk}/",
            {"as_published": "on", "device": "unknown"},
        )
        self.assertContains(response, "global-expired")
        self.link.refresh_from_db()
        self.assertEqual(self.link.state, "draft")

    def test_duplicate_cannot_bypass_creation_limit(self):
        Link.objects.bulk_create(
            [
                Link(workspace=self.workspace, destination="https://example.org")
                for _ in range(99)
            ]
        )
        response = self.client.post(
            f"/manage/links/{self.link.pk}/action/",
            {"action": "duplicate", "version": 1},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Link.objects.count(), 100)

    def test_xss_is_escaped(self):
        self.link.name = "<script>alert(1)</script>"
        self.link.save()
        response = self.client.get("/manage/")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_db_failure_is_safe_and_readiness_reports_unavailable(self):
        with patch(
            "links.views.Alias.objects.select_related",
            side_effect=DatabaseError("DB停止"),
        ):
            self.assertEqual(
                self.client.get("/sample", HTTP_HOST="localhost").status_code, 503
            )
        with patch("django.db.connection.cursor", side_effect=DatabaseError("DB停止")):
            self.assertEqual(self.client.get("/health/ready/").status_code, 503)

    def test_manager_referrer_policy_keeps_csrf_origin(self):
        self.assertEqual(
            self.client.get("/manage/login/")["Referrer-Policy"], "same-origin"
        )
        self.assertEqual(
            self.client.get("/sample", HTTP_HOST="localhost")["Referrer-Policy"],
            "no-referrer",
        )

    def test_stopping_is_possible_during_destination_dns_failure(self):
        with patch(
            "links.services.validate_public_dns", side_effect=ValidationError("DNS停止")
        ):
            stopped = update_link(
                self.link.pk, self.workspace, self.user, {"state": "paused"}, 1
            )
            self.assertEqual(stopped.state, "paused")
            with self.assertRaises(ValidationError):
                update_link(
                    stopped.pk, self.workspace, self.user, {"state": "published"}, 2
                )

    def test_abuse_stop_survives_revision_restore(self):
        from .services import set_blocked

        stopped = set_blocked(self.link.pk, self.workspace, self.user, 1, True)
        restored = restore_link(
            stopped, self.user, self.link.revisions.get(version=1), 2
        )
        self.assertTrue(restored.blocked)
        self.assertEqual(resolve(restored).status, 410)

    def test_management_host_boundary(self):
        from django.test import override_settings

        with override_settings(
            ADMIN_HOST="admin.example.com",
            ALLOWED_HOSTS=["admin.example.com", "go.example.com"],
        ):
            self.assertEqual(
                self.client.get(
                    "/manage/login/", HTTP_HOST="go.example.com"
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.get("/manage/", HTTP_HOST="admin.example.com").status_code,
                200,
            )

    def test_global_settings_reject_private_dns(self):
        with patch(
            "links.forms.validate_public_dns",
            side_effect=ValidationError("内部向けDNS"),
        ):
            response = self.client.post(
                "/manage/settings/",
                {"name": "運用", "outside_destination": "https://example.org"},
            )
        self.assertContains(response, "内部向けDNS")
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.outside_destination, "")

    def test_bulk_partial_failure_rolls_back_and_same_key_can_retry(self):
        import uuid
        from .models import ConversionJob

        data = {
            "text": "前 https://example.org/a。後 https://example.org/b。",
            "mode": "position",
            "job_key": str(uuid.uuid4()),
            "selected": ["0", "1"],
            "confirm": "yes",
        }
        count = 0

        def failing_create(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise ValidationError("2件目の作成に失敗しました。再試行してください。")
            return create_link(*args, **kwargs)

        with patch("links.views.create_link", side_effect=failing_create):
            response = self.client.post("/manage/bulk/", data)
        self.assertContains(response, "再試行してください")
        self.assertEqual(Link.objects.count(), 1)
        self.assertFalse(ConversionJob.objects.exists())
        self.client.post("/manage/bulk/", data)
        self.assertEqual(Link.objects.count(), 3)
        self.assertEqual(ConversionJob.objects.count(), 1)

    def conversion_job(self):
        import uuid
        from .models import ConversionJob

        self.client.post(
            "/manage/bulk/",
            {
                "text": "前 https://example.org/a。後 https://example.org/b。",
                "mode": "position",
                "job_key": str(uuid.uuid4()),
                "selected": ["0", "1"],
                "confirm": "yes",
            },
        )
        return ConversionJob.objects.get()

    def test_bulk_publication_dns_failure_rolls_back_and_can_retry(self):
        job = self.conversion_job()
        with patch(
            "links.services.validate_public_dns",
            side_effect=[None, ValidationError("公開DNSを確認できません。")],
        ):
            response = self.client.post(f"/manage/bulk/{job.pk}/publish/")
        self.assertEqual(response.url, f"/manage/bulk/{job.pk}/")
        self.assertEqual(
            Link.objects.exclude(pk=self.link.pk).filter(state="draft").count(), 2
        )
        self.client.post(f"/manage/bulk/{job.pk}/publish/")
        self.assertEqual(
            Link.objects.exclude(pk=self.link.pk).filter(state="published").count(), 2
        )

    def test_bulk_publication_resolves_original_domain(self):
        from django.test import override_settings

        job = self.conversion_job()
        with override_settings(
            PUBLIC_HOST="new.example.com", PUBLIC_ORIGIN="https://new.example.com"
        ):
            self.client.post(f"/manage/bulk/{job.pk}/publish/")
        self.assertEqual(
            Link.objects.exclude(pk=self.link.pk).filter(state="published").count(), 2
        )

    def test_bulk_publication_does_not_resume_paused_link(self):
        job = self.conversion_job()
        link = Link.objects.exclude(pk=self.link.pk).first()
        link.state = "paused"
        link.save()
        self.client.post(f"/manage/bulk/{job.pk}/publish/")
        link.refresh_from_db()
        self.assertEqual(link.state, "paused")


class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "operator", password="secure-password-2026"
        )
        workspace = Workspace.objects.create(name="試験")
        Membership.objects.create(user=self.user, workspace=workspace)

    def test_first_login_enroll_and_recovery_token_is_single_use(self):
        from django_otp.oath import totp
        from django_otp.plugins.otp_static.models import StaticToken

        response = self.client.post(
            "/manage/login/",
            {"username": "operator", "password": "secure-password-2026"},
        )
        self.assertEqual(response.url, "/manage/mfa/")
        self.assertEqual(self.client.get("/manage/").url, "/manage/mfa/")
        self.client.get("/manage/mfa/")
        device = TOTPDevice.objects.get(user=self.user)
        code = str(
            totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)
        ).zfill(6)
        response = self.client.post("/manage/mfa/", {"token": code})
        self.assertContains(response, "回復コードを安全に保管")
        recovery = StaticToken.objects.first().token
        self.assertEqual(self.client.get("/manage/").status_code, 200)
        self.client.post("/manage/logout/")
        response = self.client.post(
            "/manage/login/",
            {
                "username": "operator",
                "password": "secure-password-2026",
                "token": recovery,
            },
        )
        self.assertEqual(response.url, "/manage/")
        self.client.post("/manage/logout/")
        response = self.client.post(
            "/manage/login/",
            {
                "username": "operator",
                "password": "secure-password-2026",
                "token": recovery,
            },
        )
        self.assertContains(response, "認証コードを確認してください")

    def test_login_throttling(self):
        for _ in range(5):
            self.client.post(
                "/manage/login/", {"username": "operator", "password": "wrong"}
            )
        response = self.client.post(
            "/manage/login/",
            {"username": "operator", "password": "secure-password-2026"},
        )
        self.assertContains(response, "試行回数の上限")

    def test_revoke_sessions(self):
        self.client.force_login(self.user)
        call_command("revoke_sessions", username="operator", verbosity=0)
        self.assertEqual(self.client.get("/manage/").url, "/manage/login/")

    def test_server_mfa_reset_revokes_enrollment_and_sessions(self):
        from django.core.management.base import CommandError

        TOTPDevice.objects.create(user=self.user, name="旧認証", confirmed=True)
        self.client.force_login(self.user)
        with self.assertRaises(CommandError):
            call_command("reset_mfa", username="operator")
        call_command(
            "reset_mfa", username="operator", identity_confirmed=True, verbosity=0
        )
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertEqual(self.client.get("/manage/").url, "/manage/login/")
