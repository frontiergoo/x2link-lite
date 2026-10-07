from django import forms
from django.core.exceptions import ValidationError
from .models import Link, Campaign, Workspace
from .services import validate_destination, validate_slug, add_utm, validate_public_dns


class LinkForm(forms.ModelForm):
    slug = forms.CharField(label="スラッグ（空欄なら自動生成）", required=False)
    tags = forms.CharField(
        label="タグ",
        required=False,
        help_text="カンマで区切ります。各64文字以内、20件まで。",
    )
    utm_source = forms.CharField(
        label="配布元（utm_source）",
        required=False,
        max_length=200,
        help_text="例：newsletter、instagram",
    )
    utm_medium = forms.CharField(
        label="媒体（utm_medium）",
        required=False,
        max_length=200,
        help_text="例：email、social、print",
    )
    utm_campaign = forms.CharField(
        label="施策名（utm_campaign）",
        required=False,
        max_length=200,
        help_text="例：autumn_2026。配布元・媒体・施策は小文字でそろえると比較しやすくなります。",
    )
    utm_overwrite = forms.BooleanField(
        label="既存のUTMを上書きすることを確認しました", required=False
    )
    expected_version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Link
        fields = [
            "name",
            "destination",
            "state",
            "campaign",
            "tags",
            "starts_at",
            "ends_at",
            "mobile_destination",
            "outside_destination",
            "note",
            "placement",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "ends_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["campaign"].queryset = Campaign.objects.filter(workspace=workspace)
        if not self.is_bound:
            self.initial["tags"] = ", ".join(self.instance.tags or [])
        if not self.instance._state.adding:
            self.fields.pop("slug")
            self.fields["expected_version"].initial = self.instance.version

    def clean_tags(self):
        import json

        raw = self.cleaned_data.get("tags", "").strip()
        # 既存のJSON形式は旧フォームとの互換入力として受け付ける。
        try:
            tags = (
                json.loads(raw)
                if raw.startswith("[")
                else [tag.strip() for tag in raw.split(",") if tag.strip()]
            )
        except ValueError:
            raise ValidationError("タグをカンマで区切って入力してください。")
        if (
            not isinstance(tags, list)
            or len(tags) > 20
            or any(not isinstance(tag, str) or len(tag) > 64 for tag in tags)
        ):
            raise ValidationError("タグは各64文字以内、20件まで指定できます。")
        return list(dict.fromkeys(tags))

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        return validate_slug(slug) if slug else ""

    def clean(self):
        data = super().clean()
        for field in ("destination", "mobile_destination", "outside_destination"):
            if data.get(field):
                try:
                    validate_destination(data[field])
                except ValidationError as e:
                    self.add_error(field, e)
        if data.get("destination") and not self.errors.get("destination"):
            try:
                data["destination"] = add_utm(
                    data["destination"],
                    data.get("utm_source", ""),
                    data.get("utm_medium", ""),
                    data.get("utm_campaign", ""),
                    data.get("utm_overwrite", False),
                )
            except ValidationError as e:
                self.add_error("destination", e)
        if (
            data.get("starts_at")
            and data.get("ends_at")
            and data["ends_at"] <= data["starts_at"]
        ):
            self.add_error("ends_at", "終了日時は開始日時より後にしてください。")
        return data


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ["name", "purpose", "starts_at", "ends_at"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean(self):
        data = super().clean()
        if (
            data.get("starts_at")
            and data.get("ends_at")
            and data["ends_at"] <= data["starts_at"]
        ):
            self.add_error("ends_at", "終了日時は開始日時より後にしてください。")
        return data


class LoginForm(forms.Form):
    username = forms.CharField(label="ユーザー名", max_length=150)
    password = forms.CharField(
        label="パスワード", max_length=512, widget=forms.PasswordInput
    )
    token = forms.CharField(
        label="認証アプリの6桁コード／回復コード",
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )


class TokenForm(forms.Form):
    token = forms.CharField(label="認証アプリの6桁コード", max_length=6)


class BulkForm(forms.Form):
    keep_text = forms.BooleanField(
        label="変換後の本文を7日間保存する（任意）", required=False
    )
    text = forms.CharField(
        label="変換する本文",
        max_length=100000,
        widget=forms.Textarea(attrs={"rows": 12}),
    )
    mode = forms.ChoiceField(
        label="計測方法",
        choices=[("position", "掲載位置ごと"), ("shared", "同じURLは共通リンク")],
    )
    campaign = forms.ModelChoiceField(
        label="キャンペーン", queryset=Campaign.objects.none(), required=False
    )

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["campaign"].queryset = Campaign.objects.filter(workspace=workspace)


class SimulationForm(forms.Form):
    as_published = forms.BooleanField(
        label="公開した場合の判定を確認する（設定は変更しません）", required=False
    )
    device = forms.ChoiceField(
        label="端末",
        choices=[
            ("unknown", "不明（既定先）"),
            ("desktop", "PC"),
            ("mobile", "スマートフォン"),
        ],
    )
    at = forms.DateTimeField(
        label="確認する日時（日本時間）",
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
    )


class AnalyticsForm(forms.Form):
    starts = forms.DateField(
        label="開始日", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    ends = forms.DateField(
        label="終了日（含む）",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    device = forms.ChoiceField(
        label="端末",
        required=False,
        choices=[
            ("", "すべて"),
            ("unknown", "不明"),
            ("desktop", "PC"),
            ("mobile", "スマートフォン"),
        ],
    )
    referrer = forms.CharField(label="参照元ドメイン", required=False, max_length=253)
    placement = forms.CharField(label="掲載位置", required=False, max_length=120)

    def clean(self):
        data = super().clean()
        if data.get("starts") and data.get("ends") and data["starts"] > data["ends"]:
            self.add_error("ends", "終了日は開始日以降を指定してください。")
        return data


class ReauthForm(forms.Form):
    password = forms.CharField(
        label="現在のパスワード", max_length=512, widget=forms.PasswordInput
    )
    token = forms.CharField(
        label="認証アプリのコード／回復コード",
        max_length=64,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )


class WorkspaceForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ["name", "outside_destination"]

    def clean_outside_destination(self):
        value = self.cleaned_data.get("outside_destination", "")
        if value:
            validate_destination(value)
            validate_public_dns(value)
        return value
