"""The Django administration site is reserved for platform operators."""

from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig

from base.platform_access import is_platform_developer


class PlatformAdminSite(AdminSite):
    def has_permission(self, request):
        return is_platform_developer(request.user) and not request.user.is_new_employee


class PlatformAdminConfig(AdminConfig):
    default_site = "base.admin_site.PlatformAdminSite"
