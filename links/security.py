import hashlib
from datetime import timedelta
from functools import wraps
from django.db import transaction
from django.db.models import F
from django.shortcuts import redirect
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.plugins.otp_static.models import StaticDevice
from .models import LoginAttempt


def verify_mfa(user, token):
    with transaction.atomic():
        for model in (TOTPDevice, StaticDevice):
            for device in model.objects.select_for_update().filter(
                user=user, confirmed=True
            ):
                if device.verify_token(token):
                    return device
    return None


def rate_key(username):
    return hashlib.sha256(username.casefold().encode()).hexdigest()


def locked(username):
    row = LoginAttempt.objects.filter(key=rate_key(username)).first()
    return bool(row and row.locked_until and row.locked_until > timezone.now())


def failed(username):
    with transaction.atomic():
        row, _ = LoginAttempt.objects.select_for_update().get_or_create(
            key=rate_key(username)
        )
        LoginAttempt.objects.filter(pk=row.pk).update(failures=F("failures") + 1)
        row.refresh_from_db()
        if row.failures >= 5:
            row.locked_until = timezone.now() + timedelta(minutes=15)
            row.failures = 0
            row.save()


def recent_auth(fn):
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        if timezone.now().timestamp() - request.session.get("verified_at", 0) > 600:
            request.session["reauth_return"] = (
                request.path if request.path.startswith("/manage/") else "/manage/"
            )
            return redirect("reauth")
        return fn(request, *args, **kwargs)

    return wrapper
