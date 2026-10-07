# Djangoによるデータベース変更定義。

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Campaign",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120, verbose_name="名前")),
                ("purpose", models.TextField(blank=True, verbose_name="目的")),
                (
                    "starts_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="開始"),
                ),
                (
                    "ends_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="終了"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Workspace",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120, verbose_name="名前")),
                (
                    "timezone",
                    models.CharField(
                        default="Asia/Tokyo", max_length=64, verbose_name="タイムゾーン"
                    ),
                ),
                (
                    "emergency_stop",
                    models.BooleanField(default=False, verbose_name="緊急停止"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Link",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "name",
                    models.CharField(blank=True, max_length=200, verbose_name="名前"),
                ),
                (
                    "destination",
                    models.URLField(max_length=4096, verbose_name="転送先URL"),
                ),
                (
                    "mobile_destination",
                    models.URLField(
                        blank=True,
                        max_length=4096,
                        verbose_name="スマートフォンの転送先",
                    ),
                ),
                (
                    "outside_destination",
                    models.URLField(
                        blank=True, max_length=4096, verbose_name="期間外の転送先"
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("draft", "下書き"),
                            ("published", "公開"),
                            ("paused", "一時停止"),
                            ("archived", "アーカイブ"),
                        ],
                        default="draft",
                        max_length=16,
                        verbose_name="公開状態",
                    ),
                ),
                (
                    "starts_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="開始日時"
                    ),
                ),
                (
                    "ends_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="終了日時"
                    ),
                ),
                ("tags", models.JSONField(default=list, verbose_name="タグ")),
                ("note", models.TextField(blank=True, verbose_name="メモ")),
                (
                    "placement",
                    models.CharField(
                        blank=True, max_length=120, verbose_name="掲載位置"
                    ),
                ),
                (
                    "blocked",
                    models.BooleanField(
                        default=False, verbose_name="不正利用による停止"
                    ),
                ),
                ("version", models.PositiveIntegerField(default=1, verbose_name="版")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "campaign",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="links.campaign",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="links.workspace",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ClickEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("device", models.CharField(max_length=16)),
                ("referrer", models.CharField(blank=True, max_length=253)),
                ("estimated", models.BooleanField(default=False)),
                ("processed", models.BooleanField(default=False)),
                (
                    "link",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="links.link"
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="campaign",
            name="workspace",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to="links.workspace"
            ),
        ),
        migrations.CreateModel(
            name="Audit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("action", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "link",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="links.link",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="links.workspace",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DailyMetric",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField()),
                ("device", models.CharField(max_length=16)),
                ("referrer", models.CharField(blank=True, max_length=253)),
                ("requests", models.PositiveIntegerField(default=0)),
                ("estimated", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "link",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="links.link"
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("link", "date", "device", "referrer"),
                        name="metric_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Alias",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("host", models.CharField(max_length=253)),
                ("path", models.CharField(max_length=256)),
                (
                    "link",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="aliases",
                        to="links.link",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("host", "path"), name="alias_unique"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Revision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                ("snapshot", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "link",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="revisions",
                        to="links.link",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("link", "version"), name="revision_unique"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Membership",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("owner", "管理者"),
                            ("editor", "編集者"),
                            ("viewer", "閲覧者"),
                        ],
                        default="owner",
                        max_length=16,
                        verbose_name="役割",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="links.workspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace", "user"), name="membership_unique"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ConversionJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.UUIDField()),
                ("fingerprint", models.CharField(max_length=64)),
                ("result", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="links.workspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace", "key"), name="conversion_unique"
                    )
                ],
            },
        ),
    ]
