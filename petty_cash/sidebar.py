from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


MENU = _("Finance")
IMG_SRC = "images/ui/wallet-outline.svg"

SUBMENUS = [
    {
        "menu": _("Petty Cash"),
        "redirect": reverse_lazy("petty-cash-cashbook"),
        "accessibility": "petty_cash.sidebar.cashbook_accessibility",
    },
]


def cashbook_accessibility(request, submenu, user_perms, *args, **kwargs):
    return request.user.has_perm("petty_cash.view_pettycashaccount")
