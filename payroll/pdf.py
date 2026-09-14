"""Offline PDF rendering with authorized local assets and no executable scripts."""

import io
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.exceptions import SuspiciousFileOperation
from django.utils._os import safe_join
from xhtml2pdf import pisa

# Unknown/remote images are omitted without making a network request.
EMPTY_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)

# xhtml2pdf does not implement flexbox and inherits some block padding. Keep
# the existing payslip tables, with compact print spacing for its layout engine.
FALLBACK_CSS = """<style>
    @page { size: a4; margin: 12mm; }
    html, body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; }
    body, div, p, span, h4, h5 { padding: 0; margin: 0; }
    .oh-payslip, .oh-payslip-container { padding: 0; margin: 0; font-size: 10pt; }
    p { margin: 4pt 0; }
    .oh-payslip_head { margin-bottom: 10pt; padding-bottom: 6pt; }
    .oh-payslip-company-name { font-size: 15pt; margin: 0 0 6pt 0; }
    .oh-payslip-company-address { font-size: 10pt; }
    .oh-payslip-secondhead h4 { font-size: 11pt; margin: 6pt 0; }
    .oh-payslip_left .oh-payslip-left-title { font-size: 10pt; }
    .oh-payslip_left .oh-payslip-left-value { font-size: 11pt; margin: 4pt 0; }
    table, table tr, table td, table th { padding: 6pt; font-size: 10pt; }
    .oh-footer-total h5 { margin: 0 0 4pt 0; }
    .mt-4 { margin-top: 10pt; }
    .oh-logo img { width: 65pt; }
</style>"""


def render_payslip_html(html_content, request=None):
    from horilla.models import has_xss

    if has_xss(html_content):
        raise ValueError("This document could not be generated safely.")

    def local_asset(uri, _relative):
        parsed = urlsplit(uri)
        if parsed.scheme not in ("", "http", "https"):
            return EMPTY_IMAGE
        if parsed.netloc and (request is None or parsed.netloc != request.get_host()):
            return EMPTY_IMAGE
        asset_path = unquote(parsed.path)
        try:
            if asset_path.startswith(settings.STATIC_URL):
                relative = asset_path[len(settings.STATIC_URL) :]
                # Reject path traversal before consulting static finders.
                safe_join(settings.STATIC_ROOT or settings.BASE_DIR, relative)
                found = finders.find(relative)
                if found and Path(found).is_file():
                    return str(found)
            if asset_path.startswith(settings.MEDIA_URL):
                from base.media_access import can_download, public_file

                relative = asset_path[len(settings.MEDIA_URL) :]
                if any(part.startswith(".") for part in relative.split("/")):
                    return EMPTY_IMAGE
                if not public_file(relative) and not can_download(
                    getattr(request, "user", None), relative
                ):
                    return EMPTY_IMAGE
                candidate = Path(safe_join(settings.MEDIA_ROOT, relative)).resolve()
                if (
                    candidate.is_relative_to(Path(settings.MEDIA_ROOT).resolve())
                    and candidate.is_file()
                ):
                    return str(candidate)
        except (ValueError, OSError, SuspiciousFileOperation):
            pass
        return EMPTY_IMAGE

    # PDFs must not depend on remote CSS or forward browser cookies to assets.
    offline_html = re.sub(r"<link\b[^>]*>", "", html_content, flags=re.I)
    if "</head>" in offline_html:
        offline_html = offline_html.replace("</head>", FALLBACK_CSS + "</head>", 1)
    else:
        offline_html = FALLBACK_CSS + offline_html
    output = io.BytesIO()
    result = pisa.CreatePDF(offline_html, dest=output, link_callback=local_asset)
    if result.err:
        raise ValueError("Payslip PDF rendering failed")
    return output.getvalue()
