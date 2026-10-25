from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PettyCashConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "petty_cash"
    verbose_name = _("Petty Cash")
