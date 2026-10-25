"""Small, bundled menu icons embedded in the shell for reliable first paint."""

import base64
import re
from functools import lru_cache
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders

register = template.Library()

# Used only if a future menu references a missing/unsupported bundled asset.
# Keep the menu usable without another request to a potentially missing file.
_FALLBACK = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="currentColor" d="M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z"/></svg>'


@register.simple_tag
@lru_cache(maxsize=64)
def sidebar_icon_uri(asset):
    """Embed trusted, small source assets only; never media or arbitrary paths.

    The cache lives in the worker, not the database. The image is delivered in
    the same response as its menu, avoiding separate image/cache requests on
    reload. Source files are used so this also works before collectstatic.
    """
    content, mime = _FALLBACK, "image/svg+xml"
    if isinstance(asset, str) and re.fullmatch(r"images/ui/[a-z0-9_-]+\.(svg|png)", asset):
        source = finders.find(asset)
        if source:
            try:
                with Path(source).open("rb") as icon:
                    data = icon.read(65537)
                if 0 < len(data) <= 65536:
                    content = data
                    mime = "image/png" if asset.endswith(".png") else "image/svg+xml"
            except OSError:
                pass
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"
