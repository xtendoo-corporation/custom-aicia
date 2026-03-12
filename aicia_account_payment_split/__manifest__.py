# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Payment Split Templates (AICIA)",
    "summary": """Reparto automático de cobros mediante plantillas configurables""",
    "version": "19.0.1.0.0",
    "description": """
Módulo para AICIA que permite configurar plantillas de reparto de cobros.
Al postear un pago y reconciliarlo con facturas, se genera automáticamente
un asiento contable adicional (entry) que reparte el importe pagado según
la plantilla seleccionada.

Características:
- Múltiples plantillas de reparto por compañía
- Selección manual o sugerencia automática por analítica
- Soporte multi-company y multi-currency
- Log de auditoría con trazabilidad completa
- Asiento inverso automático al cancelar
""",
    "author": "Manuel Calero, Xtendoo",
    "company": "Xtendoo",
    "website": "https://xtendoo.es",
    "category": "Accounting",
    "depends": [
        "account",
        "account_accountant",
        "analytic",
        "account_move_analytic_account",
    ],
    "license": "AGPL-3",
    "data": [
        "security/ir.model.access.csv",
        "security/account_payment_split_security.xml",
        "views/account_payment_split_template_views.xml",
        "views/account_payment_views.xml",
        "views/account_move_views.xml",
        "views/account_payment_split_log_views.xml",
        "views/account_payment_register_views.xml",
        "views/account_analytic_account_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
