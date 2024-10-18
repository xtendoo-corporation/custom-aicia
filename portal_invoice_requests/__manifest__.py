{
    "name": "Aicia portal invoice requests",
    "summary": """Aicia portal invoice requests""",
    "version": "17.0.1.0.0",
    "description": """Aicia portal invoice requests""",
    "company": "Xtendoo",
    "website": "http://www.xtendoo.es",
    "category": "Website",
    "depends": ["website", "portal", "account"],
    "license": "AGPL-3",
    "data": [
        'security/ir.model.access.csv',
        'views/portal_invoice_requests_template.xml',
    ],
    "installable": True,
    'application': False,
}
