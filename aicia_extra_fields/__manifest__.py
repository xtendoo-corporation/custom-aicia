{
    "name": "AICIA - Campos extra",
    "author": "Xtendoo",
    "category": "Extra Tools",
    "version": "19.0.1.0.4",
    "depends": [
        "base",
        "purchase",
        "sale",
        "hr",
    ],
    "license": "AGPL-3",
    "application": True,
    "description": """
        Wizard para importar proveedores, clientes y personal desde archivos Excel.
        """,
    "data": [
        "views/res_partner.xml",
        "views/hr_employee.xml",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "installable": True,
}

