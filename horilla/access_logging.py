"""Gunicorn logging that does not retain employee password-reset links."""

from gunicorn.glogging import Logger

from horilla.credential_urls import redact_reset_urls


class CredentialSafeLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        return {name: redact_reset_urls(value) for name, value in atoms.items()}
