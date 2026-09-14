"""Explicit bulk-edit fields; identity and company assignments are never writable."""

from rest_framework import serializers

from base.auth_backends import get_home_company_id
from employee.models import Employee, EmployeeWorkInformation


class BulkFieldsMixin:
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"non_field_errors": ["Expected an object of fields to update."]}
            )
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {
                    field: "This field cannot be changed using bulk update."
                    for field in unknown
                }
            )
        return super().to_internal_value(data)

    def get_fields(self):
        fields = super().get_fields()
        company_id = get_home_company_id(self.context["request"].user)
        for field in fields.values():
            queryset = getattr(field, "queryset", None)
            if queryset is None:
                continue
            if queryset.model is Employee:
                field.queryset = queryset.filter(
                    employee_work_info__company_id=company_id
                )
            else:
                manager = queryset.model._default_manager
                if hasattr(manager, "get_company_filter_path"):
                    from django.db.models import Q

                    path = manager.get_company_filter_path()
                    if path:
                        field.queryset = queryset.filter(
                            Q(**{path: company_id}) | Q(**{path + "__isnull": True})
                        ).distinct()
        return fields


class BulkEmployeeSerializer(BulkFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = (
            "experience",
            "gender",
            "dob",
            "country",
            "state",
            "city",
            "address",
            "zip",
            "marital_status",
            "children",
            "qualification",
            "emergency_contact",
            "emergency_contact_name",
            "emergency_contact_relation",
        )


class BulkWorkInformationSerializer(BulkFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = EmployeeWorkInformation
        fields = (
            "email",
            "mobile",
            "department_id",
            "job_position_id",
            "job_role_id",
            "shift_id",
            "work_type_id",
            "reporting_manager_id",
            "employee_type_id",
            "location",
            "date_joining",
            "basic_salary",
            "salary_hour",
            "contract_end_date",
        )
