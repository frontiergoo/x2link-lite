from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.plugins.otp_static.models import StaticDevice
from links.models import Audit, Membership


class Command(BaseCommand):
    help = "本人確認済みの利用者のMFAを再登録状態に戻し、全セッションを失効します。"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--identity-confirmed", action="store_true")

    def handle(self, *args, **options):
        if not options["identity_confirmed"]:
            raise CommandError(
                "運用責任者が本人確認を行ってから--identity-confirmedを指定してください。"
            )
        with transaction.atomic():
            user = (
                get_user_model()
                .objects.select_for_update()
                .filter(username=options["username"])
                .first()
            )
            if not user:
                raise CommandError("利用者が見つかりません。")
            TOTPDevice.objects.filter(user=user).delete()
            StaticDevice.objects.filter(user=user).delete()
            for membership in Membership.objects.filter(user=user):
                Audit.objects.create(
                    workspace=membership.workspace,
                    actor=user,
                    action="本人確認後のMFA再登録",
                )
            call_command("revoke_sessions", username=user.username)
        self.stdout.write(
            "MFAを再登録状態に戻しました。本人がログインし直して認証アプリと回復コードを設定してください。"
        )
