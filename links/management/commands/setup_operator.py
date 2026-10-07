import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from links.models import Membership, Workspace


class Command(BaseCommand):
    help = "サーバー上で管理者を安全に作成します。公開登録経路は用意しません。"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--workspace", default="リンク運用")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(username=options["username"]).exists():
            raise CommandError("同名のユーザーが存在します。")
        password = getpass.getpass("パスワード（12文字以上）: ")
        if password != getpass.getpass("確認のため再入力: "):
            raise CommandError("パスワードが一致しません。")
        user = User(username=options["username"])
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages))
        user.set_password(password)
        user.save()
        workspace = Workspace.objects.first() or Workspace.objects.create(
            name=options["workspace"]
        )
        Membership.objects.create(workspace=workspace, user=user, role="owner")
        self.stdout.write(
            self.style.SUCCESS(
                "管理者を作成しました。初回ログイン時にMFAを設定してください。"
            )
        )
