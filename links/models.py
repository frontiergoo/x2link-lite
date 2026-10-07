import uuid
from django.conf import settings
from django.db import models


class Workspace(models.Model):
    name = models.CharField("名前", max_length=120)
    timezone = models.CharField("タイムゾーン", max_length=64, default="Asia/Tokyo")
    outside_destination = models.URLField(
        "既定の期間外転送先", max_length=4096, blank=True
    )
    emergency_stop = models.BooleanField("緊急停止", default=False)


class Membership(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(
        "役割",
        max_length=16,
        choices=[("owner", "管理者"), ("editor", "編集者"), ("viewer", "閲覧者")],
        default="owner",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"], name="membership_unique"
            )
        ]


class Campaign(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    name = models.CharField("名前", max_length=120)
    purpose = models.TextField("目的", blank=True)
    starts_at = models.DateTimeField("開始", null=True, blank=True)
    ends_at = models.DateTimeField("終了", null=True, blank=True)


class Link(models.Model):
    STATES = [
        ("draft", "下書き"),
        ("published", "公開"),
        ("paused", "一時停止"),
        ("archived", "アーカイブ"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    name = models.CharField("名前", max_length=200, blank=True)
    destination = models.URLField("転送先URL", max_length=4096)
    mobile_destination = models.URLField(
        "スマートフォンの転送先", max_length=4096, blank=True
    )
    outside_destination = models.URLField("期間外の転送先", max_length=4096, blank=True)
    state = models.CharField("公開状態", max_length=16, choices=STATES, default="draft")
    starts_at = models.DateTimeField("開始日時", null=True, blank=True)
    ends_at = models.DateTimeField("終了日時", null=True, blank=True)
    campaign = models.ForeignKey(
        Campaign, null=True, blank=True, on_delete=models.SET_NULL
    )
    tags = models.JSONField("タグ", default=list, blank=True)
    note = models.TextField("メモ", blank=True)
    placement = models.CharField("掲載位置", max_length=120, blank=True)
    deleted_at = models.DateTimeField("削除日時", null=True, blank=True)
    blocked = models.BooleanField("不正利用による停止", default=False)
    version = models.PositiveIntegerField("版", default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Alias(models.Model):
    link = models.ForeignKey(Link, related_name="aliases", on_delete=models.PROTECT)
    host = models.CharField(max_length=253)
    path = models.CharField(max_length=256)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["host", "path"], name="alias_unique")
        ]


class Revision(models.Model):
    link = models.ForeignKey(Link, related_name="revisions", on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["link", "version"], name="revision_unique")
        ]


class Audit(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    link = models.ForeignKey(Link, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)
    version = models.PositiveIntegerField(null=True)
    changes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def change_labels(self):
        from .review import LABELS

        return [LABELS.get(field, "設定項目") for field in self.changes]


class ClickEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    link = models.ForeignKey(Link, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    device = models.CharField(
        max_length=16,
        choices=[("unknown", "不明"), ("desktop", "PC"), ("mobile", "スマートフォン")],
    )
    referrer = models.CharField(max_length=253, blank=True)
    response_status = models.PositiveSmallIntegerField(default=302)
    rule_version = models.PositiveSmallIntegerField(default=1)
    estimated = models.BooleanField(default=False)
    processed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["processed", "created_at"], name="event_pending_time")
        ]


class DailyMetric(models.Model):
    link = models.ForeignKey(Link, on_delete=models.CASCADE)
    date = models.DateField()
    device = models.CharField(
        max_length=16,
        choices=[("unknown", "不明"), ("desktop", "PC"), ("mobile", "スマートフォン")],
    )
    referrer = models.CharField(max_length=253, blank=True)
    requests = models.PositiveIntegerField(default=0)
    estimated = models.PositiveIntegerField(default=0)
    successes = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["link", "date", "device", "referrer"], name="metric_unique"
            )
        ]


class ConversionJob(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "key"], name="conversion_unique"
            )
        ]


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True)


class WorkerState(models.Model):
    name = models.CharField(max_length=64, unique=True)
    last_run = models.DateTimeField(null=True)
    processed_total = models.PositiveBigIntegerField(default=0)
