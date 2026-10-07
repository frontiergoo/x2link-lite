from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from playwright.sync_api import sync_playwright, expect
from axe_playwright_python.sync_playwright import Axe
from .models import Alias, Link, Membership, Workspace


class BrowserAcceptanceTests(StaticLiveServerTestCase):
    def test_create_publish_stop_restore_and_accessibility(self):
        user = get_user_model().objects.create_user(
            "browser_operator", password="browser-test-password-2026"
        )
        workspace = Workspace.objects.create(name="ブラウザー検証")
        Membership.objects.create(user=user, workspace=workspace)
        artifacts = Path(settings.BASE_DIR) / "artifacts" / "browser"
        artifacts.mkdir(parents=True, exist_ok=True)
        with (
            ThreadPoolExecutor(max_workers=1) as database_thread,
            sync_playwright() as playwright,
            override_settings(PUBLIC_ORIGIN=self.live_server_url),
        ):
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.set_default_timeout(10000)
            page.context.grant_permissions(["clipboard-read", "clipboard-write"])
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + "/manage/login/")
            page.get_by_label("ユーザー名").fill("browser_operator")
            page.get_by_label("パスワード").fill("browser-test-password-2026")
            page.get_by_role("button", name="ログイン", exact=True).click()
            if page.get_by_role("heading", name="アクセス禁止 (403)").count():
                self.fail(page.locator("body").inner_text()[:1800])
            expect(page.get_by_role("heading", name="認証アプリを設定")).to_be_visible()
            device = database_thread.submit(
                lambda: TOTPDevice.objects.get(user=user)
            ).result()
            code = str(
                totp(
                    device.bin_key, step=device.step, t0=device.t0, digits=device.digits
                )
            ).zfill(6)
            page.get_by_label("認証アプリの6桁コード").fill(code)
            page.get_by_role("button", name="設定を完了").click()
            page.get_by_role("link", name="保管してリンク一覧へ").click()
            expect(
                page.get_by_role("heading", name="リンク一覧", exact=True)
            ).to_be_visible()
            page.screenshot(path=str(artifacts / "desktop-empty.png"), full_page=True)
            page.get_by_role("link", name="＋ リンクを作成").click()
            page.get_by_label("転送先URL").fill("https://example.com/offer")
            page.get_by_label("名前").fill("秋のご案内")
            page.get_by_label("公開状態").select_option("published")
            page.get_by_role("button", name="保存する").click()
            expect(
                page.get_by_role("heading", name="秋のご案内", exact=True)
            ).to_be_visible()
            link = database_thread.submit(
                lambda: Link.objects.get(name="秋のご案内")
            ).result()
            alias = database_thread.submit(
                lambda: Alias.objects.get(link=link)
            ).result()
            page.get_by_role("button", name="コピー", exact=True).first.click()
            expect(page.get_by_role("button", name="コピーしました")).to_be_visible()
            self.assertEqual(
                page.evaluate("navigator.clipboard.readText()"),
                self.live_server_url + "/" + alias.path,
            )
            public = page.request.get(
                self.live_server_url + "/" + alias.path, max_redirects=0
            )
            self.assertEqual(public.status, 302)
            self.assertEqual(public.headers["location"], "https://example.com/offer")
            self.assertIn("no-store", public.headers["cache-control"])
            page.on("dialog", lambda dialog: dialog.accept())
            page.get_by_role("button", name="一時停止", exact=True).click()
            expect(page.locator(".badge")).to_have_text("一時停止")
            self.assertEqual(
                page.request.get(
                    self.live_server_url + "/" + alias.path, max_redirects=0
                ).status,
                410,
            )
            page.get_by_role("button", name="この版を復元").last.click()
            expect(page.locator(".badge")).to_have_text("公開")
            self.assertEqual(
                page.request.get(
                    self.live_server_url + "/" + alias.path, max_redirects=0
                ).status,
                302,
            )
            for path in [
                "/manage/",
                f"/manage/links/{link.pk}/",
                "/manage/links/new/",
                "/manage/bulk/",
                "/manage/campaigns/",
                "/manage/operations/",
                "/usage/",
            ]:
                page.goto(self.live_server_url + path)
                result = Axe().run(
                    page,
                    options={
                        "runOnly": {
                            "type": "tag",
                            "values": [
                                "wcag2a",
                                "wcag2aa",
                                "wcag21a",
                                "wcag21aa",
                                "wcag22aa",
                            ],
                        },
                        "resultTypes": ["violations"],
                    },
                )
                violations = result.response["violations"]
                self.assertFalse(
                    violations,
                    f"{path}: " + str([(v["id"], v["impact"]) for v in violations]),
                )
            page.goto(self.live_server_url + "/manage/bulk/")
            original_text = "前 https://example.org/a。後 https://example.org/b。"
            page.get_by_label("変換する本文").fill(original_text)
            page.get_by_label("計測方法").select_option("position")
            page.get_by_role("button", name="候補を確認", exact=True).click()
            expect(page.locator(".candidate")).to_have_count(2)
            page.locator(".candidate input").nth(1).uncheck()
            page.get_by_role("button", name="選択したURLを下書きに変換").click()
            converted = page.get_by_label("変換済み本文").input_value()
            self.assertIn("https://example.org/b", converted)
            self.assertNotIn("https://example.org/a", converted)
            page.get_by_role("button", name="本文をコピー", exact=True).click()
            expect(page.get_by_role("button", name="コピーしました")).to_be_visible()
            self.assertEqual(page.evaluate("navigator.clipboard.readText()"), converted)
            page.get_by_role("button", name="生成したリンクを公開", exact=True).click()
            generated = database_thread.submit(
                lambda: Link.objects.get(placement="掲載位置 1")
            ).result()
            self.assertEqual(generated.state, "published")
            page.goto(self.live_server_url + "/manage/")
            page.set_viewport_size({"width": 320, "height": 800})
            page.screenshot(path=str(artifacts / "mobile-links.png"), full_page=True)
            self.assertLessEqual(
                page.evaluate("document.documentElement.scrollWidth"), 320
            )
            for path in [
                f"/manage/links/{link.pk}/",
                "/manage/links/new/",
                "/manage/bulk/",
            ]:
                page.goto(self.live_server_url + path)
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), 320, path
                )
            page.goto(self.live_server_url + "/manage/")
            page.keyboard.press("Tab")
            self.assertTrue(
                page.evaluate("document.activeElement.tagName")
                in ("A", "BUTTON", "INPUT", "SELECT")
            )
            self.assertEqual(errors, [])
            browser.close()
