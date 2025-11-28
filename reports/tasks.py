# apps/reports/tasks.py

from datetime import date, timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Report, ReportType
from .services import ReportContext, ReportGeneratorService

User = get_user_model()


def _get_period(period: str) -> tuple[date, date]:
    """
    period: daily|weekly|monthly
    """
    today = timezone.now().date()

    if period == "daily":
        d_to = today - timedelta(days=1)
        d_from = d_to
    elif period == "weekly":
        d_to = today - timedelta(days=1)
        d_from = d_to - timedelta(days=6)
    else:  # monthly
        d_to = today
        d_from = d_to.replace(day=1)
    return d_from, d_to


@shared_task
def generate_periodic_reports(period: str = "monthly") -> None:
    """
    Периодическая генерация отчётов по всем типам.

    Использовать через beat:
      - еженедельно/ежемесячно в зависимости от бизнес-логики.
    """
    date_from, date_to = _get_period(period)

    ctx = ReportContext(date_from=date_from, date_to=date_to)
    system_user = None  # можно привязать к тех. пользователю, если нужен

    for report_type in ReportType.values:
        data = ReportGeneratorService.generate_report(report_type, ctx)
        report = Report.objects.create(
            type=report_type,
            date_from=date_from,
            date_to=date_to,
            generated_by=system_user,
            data=data,
        )
        ReportGeneratorService.attach_pdf(report)
