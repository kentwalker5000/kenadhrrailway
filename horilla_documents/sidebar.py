from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


MENU = _("Documents")
IMG_SRC = "images/ui/document.png"

SUBMENUS = [
    {
        "menu": _("HR Document Library"),
        "redirect": reverse_lazy("hr-document-library"),
        "accessibility": "horilla_documents.sidebar.library_accessibility",
    },
]


def library_accessibility(request, submenu, user_perms, *args, **kwargs):
    return request.user.has_perm("horilla_documents.view_hrdocumentfolder")
