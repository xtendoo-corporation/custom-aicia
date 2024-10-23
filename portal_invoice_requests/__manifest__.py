{
    "name": "Aicia portal invoice requests",
    "summary": """Aicia portal invoice requests""",
    "version": "17.0.1.0.0",
    "description": """Aicia portal invoice requests""",
    "company": "Xtendoo",
    "website": "http://www.xtendoo.es",
    "category": "Website",
    "depends": ["website", "portal", "account", "mail", "partner_multi_company", "l10n_es_edi_facturae"],
    "license": "AGPL-3",
    "data": [
        'security/ir.model.access.csv',
        'views/portal_invoice_requests_template.xml',
        'views/portal_project_requests_template.xml',
        'views/portal_purchase_order_requests_template.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'portal_invoice_requests/static/src/js/reason_codes.js',
        ],
    },
    "installable": True,
    'application': False,
}
