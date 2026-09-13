/* Resume HTMX's original request after confirmation, including its form/CSRF data. */
(function () {
    if (window.__kenadHrHtmxConfirmInstalled) return;
    window.__kenadHrHtmxConfirmInstalled = true;
    const pending = new WeakSet();

    document.addEventListener("htmx:confirm", function (event) {
        const detail = event.detail;
        if (event.defaultPrevented || !detail || !detail.question || !detail.elt ||
            typeof detail.issueRequest !== "function") return;

        event.preventDefault();
        if (pending.has(detail.elt)) return;
        pending.add(detail.elt);

        // Do not reconstruct the request from window.event or private HTMX data.
        // Those may reference a nested icon or have gone away during an async swap.
        Promise.resolve(Swal.fire({
            text: detail.question,
            icon: "question",
            showCancelButton: true,
            confirmButtonColor: "#008000",
            cancelButtonColor: "#6c757d",
            confirmButtonText: i18nMessages.confirm,
            cancelButtonText: i18nMessages.cancel,
        })).then(function (result) {
            if (result.isConfirmed) return detail.issueRequest(true);
        }).catch(function () {
            // A dismissed dialog or failed request must never trigger a retry.
        }).finally(function () {
            pending.delete(detail.elt);
        });
    });
})();
