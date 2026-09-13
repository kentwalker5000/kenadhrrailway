"""Employee reset links: fixed origin, company mail, bounded requests and tokens."""

import logging
from contextvars import copy_context
from threading import Thread
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import close_old_connections, connections
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import get_language, override

from base.backends import ConfiguredEmailBackend
from base.models import DynamicEmailConfiguration
from employee.models import Employee
from horilla.horilla_middlewares import set_selected_company

logger = logging.getLogger(__name__)


def reset_employee(user):
    return Employee._base_manager.filter(employee_user_id=user).select_related(
        "employee_user_id", "employee_work_info__company_id"
    ).first()


def reset_recipient(employee):
    info = getattr(employee, "employee_work_info", None)
    return (getattr(info, "email", "") or "").strip() or (employee.email or "").strip()


def reset_eligible(employee):
    if employee is None or not employee.is_active:
        return False
    user = employee.employee_user_id
    info = getattr(employee, "employee_work_info", None)
    company = getattr(info, "company_id", None)
    if not user or not user.is_active or not user.has_usable_password() or not company or not company.is_active:
        return False
    try:
        validate_email(reset_recipient(employee))
    except ValidationError:
        return False
    return True


def can_reset_employee(user, employee):
    """Match the profile action's permissions, with an explicit company boundary."""
    from base.auth_backends import get_home_company_id
    from base.methods import check_manager

    if not user.is_authenticated or employee is None:
        return False
    info = getattr(employee, "employee_work_info", None)
    company_id = getattr(info, "company_id_id", None)
    if not company_id or company_id != get_home_company_id(user):
        return False
    return (
        user.pk == employee.employee_user_id_id
        or user.has_perm("employee.add_employee")
        or check_manager(getattr(user, "employee_get", None), employee)
    )


class EmployeeResetTokenGenerator(PasswordResetTokenGenerator):
    def check_token(self, user, token):
        return bool(user and reset_eligible(reset_employee(user)) and super().check_token(user, token))

    def _make_hash_value(self, user, timestamp):
        employee = reset_employee(user)
        info = getattr(employee, "employee_work_info", None)
        # Django already binds to the password and last login. Also invalidate a
        # link when the actual delivery address, company or account state changes.
        state = (
            getattr(info, "company_id_id", None),
            reset_recipient(employee) if employee else "",
            getattr(employee, "is_active", False),
            user.is_active,
        )
        return super()._make_hash_value(user, timestamp) + repr(state)


employee_reset_token = EmployeeResetTokenGenerator()


def reset_origin():
    """Never build credential links from Host headers or Django's example.com Site."""
    origin = getattr(settings, "PASSWORD_RESET_BASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(origin)
    local_http = (
        settings.DEBUG and not getattr(settings, "IS_PRODUCTION", False)
        and parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    )
    if (
        not parsed.hostname or (parsed.scheme != "https" and not local_http)
        or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
        or any(character.isspace() for character in origin)
    ):
        raise ImproperlyConfigured("Set PASSWORD_RESET_BASE_URL to the employee-facing HTTPS origin.")
    # Accessing port also validates malformed port numbers.
    parsed.port
    return origin


def reset_request_allowed(request, username):
    """Shared-cache limits apply to both known and unknown usernames, and both routes."""
    window = 3600
    scopes = (
        ("ip", request.META.get("REMOTE_ADDR", "unknown"), 20),
        ("account", username.casefold(), 5),
    )
    try:
        for scope, value, limit in scopes:
            digest = salted_hmac("kenadhr-password-reset", value).hexdigest()
            key = f"password-reset:{scope}:{digest}"
            count = 1 if cache.add(key, 1, timeout=window) else cache.incr(key)
            if count > limit:
                return False
    except Exception as error:
        # Fail closed if the shared limiter is unavailable, without exposing details.
        logger.warning("Password reset limiter unavailable (%s)", type(error).__name__)
        return False
    return True


def send_employee_reset_link(employee):
    """Send to the registered address only; return True on SMTP acceptance."""
    if not reset_eligible(employee):
        return False
    company_id = employee.employee_work_info.company_id_id
    configuration = DynamicEmailConfiguration._base_manager.filter(company_id=company_id).first()
    if configuration is None:
        configuration = DynamicEmailConfiguration._base_manager.filter(
            company_id__isnull=True, is_primary=True
        ).first()
    if not configuration or not configuration.host:
        raise ImproperlyConfigured("Company mail server is not configured.")
    validate_email(configuration.from_email)
    user = employee.employee_user_id
    reset_url = reset_origin() + reverse("password_reset_confirm", kwargs={
        "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": employee_reset_token.make_token(user),
    })
    context = {
        "reset_url": reset_url,
        "username": user.username,
        "company": employee.employee_work_info.company_id.company,
        "timeout_minutes": max(1, settings.PASSWORD_RESET_TIMEOUT // 60),
    }
    backend = ConfiguredEmailBackend(configuration=configuration, fail_silently=False)
    message = EmailMultiAlternatives(
        "Reset your password - KenadHr",
        render_to_string("registration/kenadhr_password_reset_email.txt", context),
        backend.dynamic_from_email_with_display_name,
        [reset_recipient(employee)],
        reply_to=[configuration.from_email], connection=backend,
    )
    message.attach_alternative(
        render_to_string("registration/kenadhr_password_reset_email.html", context), "text/html"
    )
    # Isolate the recipient's mail-log company from an anonymous or HR request.
    def send_scoped():
        set_selected_company(str(company_id))
        return message.send() == 1

    return copy_context().run(send_scoped)


class PasswordResetMailThread(Thread):
    """Keep public responses independent of account existence and SMTP latency."""

    def __init__(self, username):
        super().__init__()
        self.username = username
        self.language = get_language()

    def run(self):
        from django.contrib.auth import get_user_model

        close_old_connections()
        try:
            with override(self.language):
                user = get_user_model()._base_manager.filter(username=self.username).first()
                if user:
                    send_employee_reset_link(reset_employee(user))
        except Exception as error:
            # Never log addresses, reset URLs/tokens, usernames, or SMTP replies.
            logger.warning("Password reset mail failed (%s)", type(error).__name__)
        finally:
            connections.close_all()
