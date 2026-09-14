"""Account provisioning never derives passwords from personal information."""

from secrets import token_urlsafe


def initial_password():
    # A usable, unguessable password lets Django's existing email recovery flow
    # activate the account. The random value is never emailed or displayed.
    return token_urlsafe(48)
