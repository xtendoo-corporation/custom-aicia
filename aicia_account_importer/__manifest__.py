# Copyright 2026 Xtendoo - https://www.xtendoo.es/
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "AICIA - Importador de Apuntes Contables",
    "author": "Xtendoo",
    "category": "Accounting",
    "version": "19.0.1.0.2",
    "depends": ["account"],
    "license": "AGPL-3",
    "application": True,
    "description": """
        Wizard para importar apuntes contables desde archivos Excel
        de aplicaciones legadas. Aplica las cuentas colectivas 400/430
        del Plan General Contable español, evitando subcuentas por tercero.
    """,
    "data": [
        "security/ir.model.access.csv",
        "wizard/aicia_account_importer_wizard.xml",
        "views/aicia_account_importer_menu.xml",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "installable": True,
}
