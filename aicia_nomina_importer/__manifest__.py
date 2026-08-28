{
    "name": "AICIA - Importador de Nóminas",
    "author": "Dani Domínguez (xtendoo)",
    "category": "Human Resources",
    "version": "19.0.1.0.0",
    "depends": [
        "hr",
        "aicia_importer",
    ],
    "license": "AGPL-3",
    "application": False,
    "description": """
        Wizard para importar información de nóminas desde archivos Excel.
        Permite la carga masiva de datos de nómina asociados a empleados
        previamente importados o existentes en el sistema.
    """,
    "data": [
        "security/ir.model.access.csv",
        "wizard/import_nomina_views.xml",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "installable": True,
}
