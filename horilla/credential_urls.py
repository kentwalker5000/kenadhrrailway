"""Redact password-reset credentials before URLs reach application/access logs."""

import re

_RESET_URL = re.compile(r"(/(?:accounts/)?reset/)[^/\s?#\"<>]+/[^/\s?#\"<>]+/?", re.I)


def redact_reset_urls(value):
    if isinstance(value, str):
        return _RESET_URL.sub(r"\1[redacted]/", value)
    return value
