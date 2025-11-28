# apps/reports/serializers.py

from datetime import date

from django.utils import timezone
from rest_framework import serializers

from .models import Report, ReportType


class ReportSerializer(serializers.ModelSerializer):
    """Базовый сериализатор отчёта для чтения/списка."""

    class Meta:
        model = Report
        fields = [
            "id",
            "type",
            "date_from",
            "date_to",
            "generated_by",
            "data",
            "pdf_file",
            "created_at",
        ]
        read_only_fields = ["generated_by", "data", "pdf_file", "created_at"]


class ReportGenerateSerializer(serializers.Serializer):
    """
    Входные данные для генерации отчёта.

    Пример:
    {
      "type": "sales",
      "date_from": "2025-01-01",
      "date_to": "2025-01-31",
      "city_id": 1,
      "partner_id": 10,
      "store_id": 5
    }
    """

    type = serializers.ChoiceField(choices=ReportType.choices)
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    city_id = serializers.IntegerField(required=False, allow_null=True)
    partner_id = serializers.IntegerField(required=False, allow_null=True)
    store_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        date_from: date = attrs["date_from"]
        date_to: date = attrs["date_to"]
        if date_from > date_to:
            raise serializers.ValidationError("date_from не может быть больше date_to")
        # лёгкая защита от совсем абсурдных дат
        if date_to > timezone.now().date() + timezone.timedelta(days=1):
            raise serializers.ValidationError("date_to не может быть в далёком будущем")
        return attrs

    def get_filters(self) -> dict:
        """Преобразовать входные фильтры в dict для сервисного слоя."""
        return {
            "city_id": self.validated_data.get("city_id"),
            "partner_id": self.validated_data.get("partner_id"),
            "store_id": self.validated_data.get("store_id"),
        }
