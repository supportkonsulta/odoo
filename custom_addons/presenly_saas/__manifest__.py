{
    'name': 'Presenly SaaS',
    'version': '19.0.1.2.0',
    'category': 'Productivity',
    'summary': 'Langganan Presenly SaaS untuk instalasi Odoo ini',
    'description': """
Presenly SaaS
=======================

Menghubungkan instalasi Odoo ini dengan control plane SaaS Presenly.

- Menyimpan konfigurasi koneksi (base URL, tenant code, API key) pada halaman
  pengaturan milik modul ini sendiri.
- Menarik status langganan dari ``GET /api/external/v1/subscription`` dan
  menyimpannya sebagai snapshot per company.
- Menampilkan banner peringatan di backend saat langganan mendekati atau
  melewati masa berlaku.
- Menyediakan ``presenly.saas.guard`` sebagai API Python bagi modul lain yang
  ingin menegakkan kebijakan langganan.

Modul ini tidak mengubah addon ``presenly`` maupun mewarisi model dan view
native Odoo. Kebijakan produk: full access, tanpa gating fitur per paket.
    """,
    'author': 'Presenly',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/presenly_saas_security.xml',
        'security/ir.model.access.csv',
        'data/presenly_saas_data.xml',
        'data/ir_cron_data.xml',
        'views/presenly_saas_config_views.xml',
        'views/presenly_saas_sync_log_views.xml',
        'views/presenly_saas_external_feature_views.xml',
        'views/presenly_saas_reference_views.xml',
        'views/presenly_saas_attendance_views.xml',
        'wizard/presenly_saas_pull_wizard_views.xml',
        # Menu root didefinisikan di sini. Setiap berkas yang menambah menu
        # harus dimuat SETELAHNYA, kalau tidak `parent="menu_presenly_saas_root"`
        # tidak ditemukan.
        'views/presenly_saas_menus.xml',
        'views/presenly_saas_reference_menus.xml',
        # Settings native memakai action dari menus, dan form langganan memakai
        # action settings, jadi urutannya harus begini.
        'views/res_config_settings_views.xml',
        'views/presenly_saas_subscription_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'presenly_saas/static/src/banner/presenly_saas_banner.js',
            'presenly_saas/static/src/banner/presenly_saas_banner.xml',
            'presenly_saas/static/src/banner/presenly_saas_banner.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
