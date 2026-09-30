{
    'name': 'KSG HC, HSE & GA Management',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Manajemen HC (SDM & Payroll), HSE (K3 & Jam Kerja), dan GA (Ticketing & Surat)',
    'author': 'IT KSG',
    'depends': ['base', 'mail', 'ksg_sales', 'ksg_operational'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/hc_views.xml',
        'views/hse_views.xml',
        'views/ga_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}