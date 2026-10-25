from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


MENU = _("Council")
IMG_SRC = "images/ui/employees.svg"
ACCESSIBILITY = "council.sidebar.menu_accessibility"

SUBMENUS = [
    {
        "menu": _("Council Members"),
        "redirect": reverse_lazy("council-member-list"),
        "accessibility": "council.sidebar.members_accessibility",
    },
    {
        "menu": _("Document Library"),
        "redirect": reverse_lazy("council-library"),
        "accessibility": "council.sidebar.library_accessibility",
    },
]


def members_accessibility(request, submenu, user_perms, *args, **kwargs):
    return request.user.has_perm("council.view_councilmember")


def library_accessibility(request, submenu, user_perms, *args, **kwargs):
    if request.user.has_perm("council.view_councildocument") or request.user.has_perm(
        "council.change_councildocument"
    ):
        return True
    # Explicit access to a restricted folder should make the library discoverable
    # without requiring a broad permission that would reveal shared folders.
    from council.models import CouncilLibraryFolder

    return CouncilLibraryFolder.objects.filter(allowed_users=request.user).exists() or CouncilLibraryFolder.objects.filter(
        allowed_groups__user=request.user
    ).exists()


def menu_accessibility(request, submenu, user_perms, *args, **kwargs):
    return members_accessibility(request, submenu, user_perms, *args, **kwargs) or library_accessibility(
        request, submenu, user_perms, *args, **kwargs
    )
