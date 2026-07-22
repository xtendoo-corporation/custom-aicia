# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "AICIA - Reparto de cuentas analíticas por empleado",
    "summary": "Permite asignar cuentas analíticas con porcentaje a cada empleado",
    "version": "19.0.1.0.0",
    "description": """
        Añade una pestaña 'Reparto' en la ficha del empleado para relacionar
        cuentas analíticas con un porcentaje libre por cada registro.
    """,
    "author": "Xtendoo",
    "company": "Xtendoo",
    "website": "http://www.xtendoo.es",
    "category": "Human Resources/Employees",
    "depends": [
        "hr",
        "analytic",
    ],
    "license": "AGPL-3",
    "data": [
        "security/ir.model.access.csv",
        "views/hr_employee_views.xml",
        "views/account_analytic_account_views.xml",
    ],
    "installable": True,
}

