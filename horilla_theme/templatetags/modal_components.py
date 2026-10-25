"""Keep shared modal containers unique across nested template includes."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def render_shared_modals(context):
    request = context.get("request")
    if request is None:
        return True
    # Fragment responses reuse the containers already in the page shell.
    if request.headers.get("HX-Request") == "true" and not (
        request.headers.get("HX-Sidebar-Nav") == "true"
        or request.headers.get("HX-History-Restore-Request") == "true"
    ):
        return False
    if getattr(request, "_shared_modals_rendered", False):
        return False
    request._shared_modals_rendered = True
    return True
