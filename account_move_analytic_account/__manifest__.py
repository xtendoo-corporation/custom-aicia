# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Account Move Analytic Account",
    "summary": """Añade campo de cuenta analítica en facturas""",
    "version": "18.0.1.0.0",
    "description": """Este módulo añade un campo relacionado con cuenta analítica en el modelo account.move""",
    "author": "Dani Domínguez, Xtendoo",
    "company": "Xtendoo",
    "website": "http://www.xtendoo.es",
    "category": "Accounting",
    "depends": [
        "account",
    ],
    "license": "AGPL-3",
    "data": [
        "views/account_move_views.xml",
    ],
    "installable": True,
}

