"""Public product pages, separate from company data and workspace access."""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.template import Context, Engine
from django.utils import timezone
from django.views.decorators.http import require_safe


_public_templates = Engine(
    dirs=[Path(settings.BASE_DIR) / "templates" / "public"],
    loaders=["django.template.loaders.filesystem.Loader"],
    libraries={"static": "django.templatetags.static"},
)


@require_safe
def welcome(request):
    # Bypass the app's database-backed template overrides and request context
    # processors. Public content must never depend on company/employee records.
    return HttpResponse(
        _public_templates.get_template("home.html").render(
            Context({"current_year": timezone.now().year})
        )
    )


@require_safe
def home(request):
    if request.user.is_authenticated:
        # Keep the existing employee/platform guard and role-aware redirects.
        from base.views import home as workspace_home

        return workspace_home(request)
    return welcome(request)
