# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "AICIA Payroll CSV Import",
    "summary": "Importa CSV de nóminas AICIA y genera el asiento contable en borrador",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "author": "Xtendoo",
    "license": "AGPL-3",
    "depends": ["base", "account", "aicia_account_menu", "aicia_employee_project_percentage"],
    "data": [
        "security/ir.model.access.csv",
        "views/payroll_config_views.xml",
        "views/payroll_import_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": False,
}
