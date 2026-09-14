"""Short-lived, single-use email challenges for API sign-in."""

import hmac
import re
import secrets
import time
from contextvars import copy_context

from django.core.cache import cache
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.utils.crypto import salted_hmac

from base.backends import ConfiguredEmailBackend
from base.models import DynamicEmailConfiguration
from base.password_reset import reset_employee, reset_recipient
from base.platform_access import is_platform_developer
from horilla.horilla_middlewares import set_selected_company

TTL = 300


def send_code(user, code):
    employee = reset_employee(user)
    company_id = None
    if employee:
        company_id = employee.employee_work_info.company_id_id
        recipient = reset_recipient(employee)
    elif is_platform_developer(user):
        recipient = user.email
    else:
        raise RuntimeError("No eligible account for email verification.")
    validate_email(recipient)
    configuration = None
    if company_id:
        configuration = DynamicEmailConfiguration._base_manager.filter(
            company_id=company_id
        ).first()
    if configuration is None:
        configuration = DynamicEmailConfiguration._base_manager.filter(
            company_id__isnull=True, is_primary=True
        ).first()
    if configuration is None:
        raise RuntimeError("Email verification is unavailable.")
    backend = ConfiguredEmailBackend(configuration=configuration, fail_silently=False)
    message = EmailMessage(
        "KenadHr verification code",
        f"Your verification code is {code}. It expires in five minutes.",
        backend.dynamic_from_email_with_display_name,
        [recipient],
        connection=backend,
    )

    def send():
        set_selected_company(company_id)
        if message.send() != 1:
            raise RuntimeError("Email verification was not accepted.")

    copy_context().run(send)


def issue_challenge(user):
    cooldown = f"kenadhr-api-otp-issue:{user.pk}"
    if not cache.add(cooldown, True, timeout=60):
        return None
    challenge = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1000000):06d}"
    key = "kenadhr-api-otp:" + challenge
    try:
        cache.set(
            key,
            {
                "user": user.pk,
                "auth": user.get_session_auth_hash(),
                "digest": salted_hmac(challenge, code).hexdigest(),
                "attempts": 0,
                "expires": time.time() + TTL,
            },
            timeout=TTL,
        )
        send_code(user, code)
    except Exception:
        cache.delete(key)
        cache.delete(cooldown)
        raise
    return challenge


def verify_challenge(user, challenge, code):
    if not isinstance(challenge, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{43}", challenge
    ):
        return False
    key = "kenadhr-api-otp:" + challenge
    lock = key + ":lock"
    if not cache.add(lock, True, timeout=10):
        return False
    try:
        record = cache.get(key)
        if not record or record["user"] != user.pk or remaining_seconds(record) == 0:
            return False
        if not hmac.compare_digest(record["auth"], user.get_session_auth_hash()):
            cache.delete(key)
            return False
        # Delete before accepting so concurrent requests cannot reuse a code.
        if isinstance(code, str) and hmac.compare_digest(
            record["digest"], salted_hmac(challenge, code).hexdigest()
        ):
            cache.delete(key)
            return True
        record["attempts"] += 1
        if record["attempts"] >= 5:
            cache.delete(key)
        else:
            # Preserve the original deadline; failed guesses must not extend it.
            cache.set(key, record, timeout=remaining_seconds(record))
        return False
    finally:
        cache.delete(lock)


def remaining_seconds(record):
    return max(0, int(record["expires"] - time.time()))
