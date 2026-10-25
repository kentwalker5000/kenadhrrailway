"""Ensure browser history receives full pages, not HTMX-only fragments."""


class HistoryRestoreMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get("HTTP_HX_HISTORY_RESTORE_REQUEST") == "true":
            # HTMX 2.0.2 sends HX-Request on history restores. Existing views
            # use that header to return table fragments, so treat this as a
            # page request. HTMX extracts hx-history-elt from the full response.
            request.META.pop("HTTP_HX_REQUEST", None)
            request.__dict__.pop("headers", None)
        return self.get_response(request)
