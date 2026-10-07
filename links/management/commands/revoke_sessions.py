from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "指定利用者のセッションを失効します。端末紛失や回復時に使用します。"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from django.core.management.base import CommandError

        user = get_user_model().objects.filter(username=options["username"]).first()
        if not user:
            raise CommandError("利用者が見つかりません。")
        count = 0
        for session in Session.objects.iterator():
            if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                session.delete()
                count += 1
        self.stdout.write(f"{count}件のセッションを失効しました。")
