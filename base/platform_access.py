"""Access checks for the KenadHr platform developer console.

Platform developers are deliberately separate from company employee accounts.
Their usernames are configured by the deployment rather than stored in a role
that a company administrator could grant to themselves.
"""

from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def is_platform_developer(user):
    """Return whether ``user`` is a configured, unassigned platform operator."""
    if not (
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.is_superuser
    ):
        return False

    configured_names = {
        name.strip().casefold()
        for name in getattr(settings, "KENADHR_PLATFORM_DEVELOPER_USERNAMES", ())
        if name and name.strip()
    }
    if user.username.casefold() not in configured_names:
        return False

    # A company account must never become a platform account. This protects
    # the one-account-to-one-company tenant boundary even if its username is
    # accidentally added to the deployment setting.
    from employee.models import Employee

    return not Employee._base_manager.filter(employee_user_id_id=user.pk).exists()


def platform_developer_required(view_func):
    """Require the dedicated developer account, returning no tenant data otherwise."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.get_full_path()}")
        if not is_platform_developer(request.user):
            raise PermissionDenied("Platform developer access is required.")
        return view_func(request, *args, **kwargs)

    return wrapped


def employee_or_platform_required(view_func):
    """Allow the platform developer at the one shared entry point only.

    The established Horilla decorator also requires an Employee record, which
    remains correct for every company page. The platform account has no such
    record, so only the home route uses this narrow bridge before it redirects
    immediately to the developer console.
    """

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if is_platform_developer(request.user):
            return view_func(request, *args, **kwargs)

        from horilla.decorators import login_required as employee_login_required

        return employee_login_required(view_func)(request, *args, **kwargs)

    return wrapped
