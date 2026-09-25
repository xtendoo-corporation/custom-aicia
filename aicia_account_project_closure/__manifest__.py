# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Cierre por Proyectos (AICIA)",
    "summary": """Automatiza el cierre contable AICIA por proyectos (cuentas analíticas),
    generando asientos de regularización 130/131 contra 294 con previsualización.""",
    "version": "19.0.1.0.0",
    "description": """
Módulo para AICIA que permite realizar el cierre contable por proyectos
(cuentas analíticas), calculando el resultado por proyecto en un rango de
fechas y generando asientos de regularización:

- Resultado positivo → cuenta 130 (Subvenciones oficiales de capital)
- Resultado negativo → cuenta 131 (Donaciones y legados de capital)
- Contrapartida → cuenta 294 (Provisiones material científico)

Características:
- Wizard con previsualización antes de generar asientos
- Reparto proporcional de analytic_distribution
- Detección de duplicados para evitar doble cierre
- Trazabilidad completa con campos técnicos en account.move
- Soporte multi-compañía
""",
    "author": "Manuel Calero, Xtendoo",
    "company": "Xtendoo",
    "website": "https://xtendoo.es",
    "category": "Accounting",
    "depends": [
        "aicia_account_menu",
        "account",
        "analytic",
    ],
    "license": "AGPL-3",
    "data": [
        "security/ir.model.access.csv",
        "views/aicia_project_closure_wizard_views.xml",
        "views/account_analytic_account_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "auto_install": False,
}

