{
    'name': 'SIF Keuangan - Jurnal Besar (MVP)',
    'version': '1.0',
    'summary': 'Master COA, Jurnal Transaksi Dasar, Buku Besar Bulanan, dan Integrasi PPL',
    'category': 'Accounting/Finance',
    'author': 'ERP SIFNEXT - Squad Keuangan',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/sif_coa_data.xml',  
        'views/coa_views.xml',
        'views/jurnal_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
}