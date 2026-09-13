"""African currency choices, verified against SIX ISO 4217 List One (2026-09-13).

Source: https://www.six-group.com/en/products-services/financial-information/market-reference-data/data-standards.html
Codes are display identifiers, not exchange rates or payroll calculation rules.
"""

from django.utils.translation import gettext_lazy as _

AFRICAN_CURRENCIES = (
    ("GHS", _("Ghanaian Cedi / Cedis (GHS)")),
    ("DZD", _("Algerian Dinar (DZD)")),
    ("AOA", _("Angolan Kwanza (AOA)")),
    ("BWP", _("Botswana Pula (BWP)")),
    ("BIF", _("Burundian Franc (BIF)")),
    ("CVE", _("Cabo Verde Escudo (CVE)")),
    ("XAF", _("Central African CFA Franc - BEAC (XAF)")),
    ("KMF", _("Comorian Franc (KMF)")),
    ("CDF", _("Congolese Franc (CDF)")),
    ("DJF", _("Djiboutian Franc (DJF)")),
    ("EGP", _("Egyptian Pound (EGP)")),
    ("ERN", _("Eritrean Nakfa (ERN)")),
    ("SZL", _("Eswatini Lilangeni (SZL)")),
    ("ETB", _("Ethiopian Birr (ETB)")),
    ("GMD", _("Gambian Dalasi (GMD)")),
    ("GNF", _("Guinean Franc (GNF)")),
    ("KES", _("Kenyan Shilling (KES)")),
    ("LSL", _("Lesotho Loti (LSL)")),
    ("LRD", _("Liberian Dollar (LRD)")),
    ("LYD", _("Libyan Dinar (LYD)")),
    ("MGA", _("Malagasy Ariary (MGA)")),
    ("MWK", _("Malawian Kwacha (MWK)")),
    ("MRU", _("Mauritanian Ouguiya (MRU)")),
    ("MUR", _("Mauritian Rupee (MUR)")),
    ("MAD", _("Moroccan Dirham (MAD)")),
    ("MZN", _("Mozambican Metical (MZN)")),
    ("NAD", _("Namibian Dollar (NAD)")),
    ("NGN", _("Nigerian Naira (NGN)")),
    ("RWF", _("Rwandan Franc (RWF)")),
    ("SHP", _("Saint Helena Pound (SHP)")),
    ("STN", _("Sao Tome and Principe Dobra (STN)")),
    ("SCR", _("Seychellois Rupee (SCR)")),
    ("SLE", _("Sierra Leonean Leone (SLE)")),
    ("SOS", _("Somali Shilling (SOS)")),
    ("ZAR", _("South African Rand (ZAR)")),
    ("SSP", _("South Sudanese Pound (SSP)")),
    ("SDG", _("Sudanese Pound (SDG)")),
    ("TZS", _("Tanzanian Shilling (TZS)")),
    ("TND", _("Tunisian Dinar (TND)")),
    ("UGX", _("Ugandan Shilling (UGX)")),
    ("XOF", _("West African CFA Franc - BCEAO (XOF)")),
    ("ZMW", _("Zambian Kwacha (ZMW)")),
    ("ZWG", _("Zimbabwe Gold / ZiG (ZWG)")),
)

OTHER_CURRENCIES = (
    ("USD", _("US Dollar (USD)")),
    ("EUR", _("Euro - including Mayotte and Reunion (EUR)")),
    ("GBP", _("Pound Sterling (GBP)")),
    ("CAD", _("Canadian Dollar (CAD)")),
    ("AUD", _("Australian Dollar (AUD)")),
    ("INR", _("Indian Rupee (INR)")),
    ("CNY", _("Chinese Yuan (CNY)")),
    ("JPY", _("Japanese Yen (JPY)")),
)


def currency_choices(current=None):
    choices = [(_("African currencies"), AFRICAN_CURRENCIES), (_("Other currencies"), OTHER_CURRENCIES)]
    known = {code for code, _label in AFRICAN_CURRENCIES + OTHER_CURRENCIES}
    if current and current not in known:
        # Do not replace old/custom symbols or historical codes just by opening
        # and saving settings. Newly selected currencies use current ISO codes.
        choices.insert(0, (_("Current saved symbol"), [(current, current)]))
    return choices


def get_currency_format(company_id=None):
    """Choose the company's row before shared defaults; never another tenant's."""
    from base.auth_backends import get_home_company_id
    from horilla.horilla_middlewares import _thread_locals, get_selected_company
    from payroll.models.tax_models import PayrollSettings

    if company_id is None:
        company_id = get_selected_company()
        if not company_id or company_id == "all":
            request = getattr(_thread_locals, "request", None)
            company_id = get_home_company_id(request.user) if request and request.user.is_authenticated else None
    rows = PayrollSettings._base_manager.order_by("pk")
    setting = rows.filter(company_id=company_id).first() if company_id else None
    if setting is None:
        setting = rows.filter(company_id__isnull=True).first()
    return (
        (setting.currency_symbol or "$") if setting else "$",
        (setting.position or "postfix") if setting else "postfix",
    )
