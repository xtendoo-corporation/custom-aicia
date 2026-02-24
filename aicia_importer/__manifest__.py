{
    "name": "AICIA - Importador de Clientes, Proveedores, Empleados y Proyectos",
    "category": "Extra Tools",
    "version": "19.0.1.0.5",
    "depends": [
        "base",
        "purchase",
        "sale",
        "hr",
        "analytic",
        "portal_requests",
    ],
    "license": "AGPL-3",
    "application": True,
    "description": """
        Wizard para importar clientes, proveedores, empleados y proyectos desde archivos Excel.
        """,
    "data": [
        "security/ir.model.access.csv",
        "wizard/aicia_importer_wizard.xml",
        "views/aicia_importer_menu.xml",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "installable": True,
}

