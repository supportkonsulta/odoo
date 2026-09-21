{
    'name': 'KSG Operational',
    'version': '19.0.1.0.0',
    'category': 'Operations',
    'summary': 'Manajemen Operasional, Perencanaan Proyek, Manpower, BoQ, dan Dokumen Penagihan KSG',
    'author': 'Tim ERP KSG',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'ksg_sales',
    ],
    'data': [
        'security/operational_security.xml',
        'security/ir.model.access.csv',
        'views/project_views.xml',
        'views/manpower_request_views.xml',
        'views/procurement_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}