{
    'name': 'Presenly SaaS: HR Integration',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Sinkronkan pegawai antara Presenly SaaS dan hr.employee',
    'description': """
Presenly SaaS: HR Integration
=============================

Menambahkan integrasi pegawai pada modul `presenly_saas`, tanpa memaksa
pemasangan HR pada instalasi yang tidak membutuhkannya.

- Cermin `presenly.saas.employee`: apa adanya yang dikirim server Presenly,
  termasuk kolom yang tidak punya padanan di Odoo.
- Sinkronisasi dua arah dengan `hr.employee` lewat `nopeg`.
- Pemberitahuan perubahan (webhook) dari server Presenly.

Karena modul ini bergantung pada `hr`, modul ini juga **menolak dipasang
bersama `hr_attendance` dan `hr_holidays`**: absensi dan cuti sudah dicerminkan
dari Presenly, jadi keduanya tidak boleh aktif bersamaan.

Rincian pemetaan kolom dan aturan konflik ada di `PLAN_HR_SYNC.md`.
    """,
    'author': 'Presenly',
    'license': 'LGPL-3',
    'depends': ['presenly_saas', 'hr'],
    'excludes': ['hr_attendance', 'hr_holidays'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/presenly_saas_employee_views.xml',
        'views/presenly_saas_employee_menus.xml',
        'views/presenly_saas_approval_hr_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_hr_views.xml',
        # Form langganan memakai action dari berkas atas, jadi dimuat terakhir.
        'views/presenly_saas_subscription_hr_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
