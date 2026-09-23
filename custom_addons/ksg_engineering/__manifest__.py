{
    'name': 'KSG Engineering',
    'version': '19.0.1.0.0',
    'category': 'Operations/Project',
    'summary': 'Modul Engineering ERP KSG',
    'description': """
Modul Engineering ERP KSG.
Menangani WBS, Master Schedule, Daily/Weekly/Monthly Report,
Approval berjenjang, Kurva-S, dan BAP/BAST digital.
Depends ke ksg_sales (single source of truth data project).
    """,
    'author': 'Tim ERP KSG',
    'depends': ['base', 'mail', 'ksg_sales'],
    'data': [
        'security/ksg_engineering_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/mail_activity_type_data.xml',
        'data/ir_cron_data.xml',
        'data/ir_config_parameter_data.xml',
        'views/ksg_sales_project_views.xml',
        'views/ksg_engineering_wbs_views.xml',
        'views/ksg_engineering_daily_report_views.xml',
        'views/ksg_engineering_consolidation_views.xml',
        'views/ksg_engineering_weekly_monthly_views.xml',
        'views/ksg_engineering_assignment_views.xml',
        'views/ksg_engineering_bapbast_views.xml',
        'views/ksg_engineering_dashboard_views.xml',
        'views/ksg_engineering_menus.xml',
        'report/bapbast_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ksg_engineering/static/src/js/kurva_s_widget.js',
            'ksg_engineering/static/src/scss/ksg_engineering.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
