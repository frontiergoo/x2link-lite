from datetime import timedelta
from django.db.models import Sum, Max
from django.utils import timezone
from .forms import AnalyticsForm
from .models import ClickEvent, DailyMetric


def report(request, links):
    form = AnalyticsForm(request.GET or None)
    metrics = DailyMetric.objects.filter(link__in=links)
    if form.is_bound and form.is_valid():
        data = form.cleaned_data
        if data["starts"]:
            metrics = metrics.filter(date__gte=data["starts"])
        if data["ends"]:
            metrics = metrics.filter(date__lte=data["ends"])
        if data["device"]:
            metrics = metrics.filter(device=data["device"])
        if data["referrer"]:
            metrics = metrics.filter(referrer__iexact=data["referrer"])
        if data["placement"]:
            metrics = metrics.filter(link__placement__icontains=data["placement"])
    elif form.is_bound:
        metrics = metrics.none()
    pending = ClickEvent.objects.filter(link__in=links, processed=False)
    oldest = pending.order_by("created_at").values_list("created_at", flat=True).first()
    return {
        "analytics_form": form,
        "metrics": metrics.select_related("link").order_by("-date")[:500],
        "total": metrics.aggregate(
            requests=Sum("requests"),
            estimated=Sum("estimated"),
            successes=Sum("successes"),
        ),
        "last_updated": metrics.aggregate(value=Max("updated_at"))["value"],
        "pending_count": pending.count(),
        "delayed": bool(oldest and oldest < timezone.now() - timedelta(minutes=5)),
        "comparison": metrics.values("link__id", "link__name", "link__placement")
        .annotate(
            requests=Sum("requests"),
            estimated=Sum("estimated"),
            successes=Sum("successes"),
        )
        .order_by("-estimated"),
    }
