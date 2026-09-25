# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "AICIA Payroll XML Import",
    "summary": "Importa XML de nóminas AICIA y genera el asiento contable en borrador",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "author": "Dani Domínguez (xtendoo.es)",
    "license": "AGPL-3",
    "depends": ["base",
                "account",
                "aicia_importer",
                ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/hr_payroll_sepa_import_wizard.xml",
    ],
    "installable": True,
    "application": False,
}
