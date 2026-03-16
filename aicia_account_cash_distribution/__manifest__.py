{
    'name': 'AICIA Cash Distribution',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localisation',
    'summary': 'Distribute income based on cash received (reconciliation)',
    'author': 'Xtendoo',
    'license': 'AGPL-3',
    'depends': ['account', 'analytic'],
    'data': [
        'security/ir.model.access.csv',
        'views/distribution_plan_views.xml',
        'views/distribution_move_views.xml',
        'views/account_payment_views.xml',
        'views/account_payment_register_views.xml',
        'views/res_config_settings_views.xml',
        'views/account_analytic_account_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

