# apps/reports/views.py

from datetime import datetime

from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .filters import ReportFilter
from .models import Report, ReportType
from .serializers import ReportGenerateSerializer, ReportSerializer
from .services import ReportContext, ReportGeneratorService


class IsAdminOrOwner(permissions.BasePermission):
    """
    Доступ к отчётам:
    - admin видит все
    - остальные только свои (generated_by == request.user)
    """

    def has_object_permission(self, request, view, obj: Report) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "role", None) == "admin" or user.is_superuser:
            return True
        return obj.generated_by_id == user.id

    def has_permission(self, request, view) -> bool:
        return request.user and request.user.is_authenticated


class ReportViewSet(viewsets.ModelViewSet):
    """
    CRUD + генерация отчётов.

    Доп. endpoints:
    - POST /reports/generate/
    - GET  /reports/{id}/diagram/
    - GET  /reports/{id}/download_pdf/
    """

    queryset = Report.objects.all().select_related("generated_by")
    serializer_class = ReportSerializer
    permission_classes = [IsAdminOrOwner]
    filterset_class = ReportFilter

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()
        if getattr(user, "role", None) == "admin" or user.is_superuser:
            return qs
        return qs.filter(generated_by=user)

    def perform_create(self, serializer):
        serializer.save(generated_by=self.request.user)

    # ---- кастомные действия ----

    @action(
        detail=False,
        methods=["post"],
        url_path="generate",
        serializer_class=ReportGenerateSerializer,
        permission_classes=[permissions.IsAuthenticated],
    )
    def generate(self, request, *args, **kwargs):
        """
        Сгенерировать новый отчёт и сохранить в БД.

        Вход: ReportGenerateSerializer.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ctx = ReportContext(
            date_from=serializer.validated_data["date_from"],
            date_to=serializer.validated_data["date_to"],
            city_id=serializer.validated_data.get("city_id"),
            partner_id=serializer.validated_data.get("partner_id"),
            store_id=serializer.validated_data.get("store_id"),
        )
        report_type = serializer.validated_data["type"]

        data = ReportGeneratorService.generate_report(report_type, ctx)
        report = Report.objects.create(
            type=report_type,
            date_from=ctx.date_from,
            date_to=ctx.date_to,
            generated_by=request.user,
            data=data,
        )
        ReportGeneratorService.attach_pdf(report)

        return Response(ReportSerializer(report).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["get"],
        url_path="diagram",
        permission_classes=[permissions.IsAuthenticated, IsAdminOrOwner],
    )
    def diagram(self, request, pk=None, *args, **kwargs):
        """Вернуть только данные для диаграммы."""
        report = self.get_object()
        return Response(report.diagram)

    @action(
        detail=True,
        methods=["get"],
        url_path="download_pdf",
        permission_classes=[permissions.IsAuthenticated, IsAdminOrOwner],
    )
    def download_pdf(self, request, pk=None, *args, **kwargs):
        """Скачать PDF отчёт."""
        from django.http import FileResponse

        report = self.get_object()
        if not report.pdf_file:
            return Response(
                {"detail": "Для этого отчёта нет PDF-файла"},
                status=status.HTTP_404_NOT_FOUND,
            )

        response = FileResponse(
            report.pdf_file.open("rb"),
            as_attachment=True,
            filename=report.pdf_file.name.split("/")[-1],
        )
        return response
