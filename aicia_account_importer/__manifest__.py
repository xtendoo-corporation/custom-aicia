# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "AICIA - Importador de Apuntes Contables",
    "author": "Xtendoo",
    "category": "Accounting",
    "version": "19.0.2.1.0",
    "depends": ["account", "aicia_account_menu"],
    "license": "AGPL-3",
    "application": True,
    "description": """
        Wizard para importar apuntes contables desde archivos Excel
        de aplicaciones legadas. Los 5 primeros dígitos de la cuenta legada
        más un 0 son la cuenta contable de Odoo y los 4 últimos el código AICIA
        del contacto asociado al apunte (único por tipo de tercero).
    """,
    "data": [
        "security/ir.model.access.csv",
        "data/aicia_account_importer_no_partner_account.xml",
        "wizard/aicia_account_importer_wizard.xml",
        "wizard/aicia_partner_code_import_wizard.xml",
        "views/account_move_views.xml",
        "views/res_partner_views.xml",
        "views/aicia_no_partner_account_views.xml",
        "views/aicia_account_importer_menu.xml",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "installable": True,
}
