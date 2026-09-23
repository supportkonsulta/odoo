{
    'name': 'Presenly SaaS',
    'version': '19.0.2.0.0',
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

Modul ini tidak mengubah addon ``presenly``, dan tidak mewarisi model native
apa pun.

Integrasi pegawai dengan ``hr.employee`` berada di modul terpisah
``presenly_saas_hr``. Pemisahan itu disengaja: modul langganan ini dipakai semua
tenant, sedangkan HR hanya sebagian. Memaksa ``hr`` di sini berarti ikut
memasang ``resource``, ``mail``, dan ``phone_validation`` pada setiap instalasi.

Kebijakan produk: full access, tanpa gating fitur per paket.
    """,
    'author': 'Presenly',
    'license': 'LGPL-3',
    # Sengaja tanpa dependensi `hr`. Integrasi pegawai berada di modul
    # terpisah `presenly_saas_hr`, supaya modul langganan ini tidak memaksa
    # pemasangan HR — beserta `resource`, `mail`, dan `phone_validation` yang
    # ikut terbawa — pada instalasi yang tidak membutuhkannya.
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/presenly_saas_security.xml',
        'security/ir.model.access.csv',
        'data/presenly_saas_data.xml',
        'data/ir_cron_data.xml',
        'views/presenly_saas_config_views.xml',
        'views/presenly_saas_sync_log_views.xml',
        'views/presenly_saas_reference_views.xml',
        'views/presenly_saas_attendance_views.xml',
        'views/presenly_saas_monitoring_views.xml',
        'views/presenly_saas_submission_views.xml',
        'views/presenly_saas_timesheet_views.xml',
        'wizard/presenly_saas_pull_wizard_views.xml',
        # Menu root didefinisikan di sini. Setiap berkas yang menambah menu
        # harus dimuat SETELAHNYA, kalau tidak `parent="menu_presenly_saas_root"`
        # tidak ditemukan.
        'views/presenly_saas_menus.xml',
        'views/presenly_saas_reconciliation_views.xml',
        'views/presenly_saas_reference_menus.xml',
        # Settings native memakai action dari menus, dan form langganan memakai
        # action settings, jadi urutannya harus begini.
        'views/res_config_settings_views.xml',
        'views/presenly_saas_subscription_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # Leaflet TIDAK didaftarkan di sini. Pustaka itu UMD dan menetapkan
            # `window.L` saat dijalankan; kalau digabung sebagai aset, penetapan
            # itu tidak sampai ke halaman dan petanya tampil kosong tanpa pesan.
            # Widget memuatnya sendiri lewat `loadJS` saat dibutuhkan.
            'presenly_saas/static/src/map/presenly_map_field.js',
            'presenly_saas/static/src/map/presenly_map_field.xml',
            'presenly_saas/static/src/map/presenly_map_field.scss',
            'presenly_saas/static/src/banner/presenly_saas_banner.js',
            'presenly_saas/static/src/banner/presenly_saas_banner.xml',
            'presenly_saas/static/src/banner/presenly_saas_banner.scss',
            'presenly_saas/static/src/approval/presenly_approval_steps.js',
            'presenly_saas/static/src/approval/presenly_approval_steps.xml',
            'presenly_saas/static/src/approval/presenly_approval_steps.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
