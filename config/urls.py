from django.urls import path
from django.http import JsonResponse
from links import views

urlpatterns = [
    path("usage/", views.usage_notice, name="usage_notice"),
    path("health/ready/", views.readiness, name="readiness"),
    path("manage/operations/", views.operations, name="operations"),
    path("health/", lambda request: JsonResponse({"状態": "稼働中"})),
    path("manage/login/", views.login_view, name="login"),
    path("manage/reauth/", views.reauthenticate, name="reauth"),
    path("manage/logout/", views.logout_view, name="logout"),
    path("manage/mfa/", views.mfa_setup, name="mfa_setup"),
    path("manage/mfa/qr/", views.mfa_qr, name="mfa_qr"),
    path("manage/", views.dashboard, name="dashboard"),
    path("manage/links/new/", views.link_create, name="link_create"),
    path("manage/links/<uuid:pk>/", views.link_detail, name="link_detail"),
    path("manage/links/<uuid:pk>/edit/", views.link_edit, name="link_edit"),
    path("manage/links/<uuid:pk>/action/", views.link_action, name="link_action"),
    path(
        "manage/links/<uuid:pk>/qr/<str:kind>/", views.qr_download, name="qr_download"
    ),
    path("manage/campaigns/<int:pk>/", views.campaign_detail, name="campaign_detail"),
    path("manage/campaigns/", views.campaigns, name="campaigns"),
    path("manage/bulk/", views.bulk_convert, name="bulk_convert"),
    path("manage/settings/", views.workspace_settings, name="workspace_settings"),
    path("manage/bulk/<int:pk>/", views.bulk_result, name="bulk_result"),
    path("manage/bulk/<int:pk>/publish/", views.bulk_publish, name="bulk_publish"),
    path("manage/export/", views.export_data, name="export_data"),
    path("manage/emergency/", views.emergency_stop, name="emergency_stop"),
    path("<path:path>", views.public_redirect, name="public_redirect"),
]
