"""Betulkan kolom proyek cermin presensi yang terisi repr payload.

Sampai versi sebelumnya, `employee.get('project')` - sebuah objek - diserahkan
apa adanya ke kolom `Char`, sehingga yang tampil di form Detail Data Presensi
adalah repr JSON-nya:

    {'id': 3, 'project_name': 'MAMBU KECUT', 'project_code': '987364', ...}

Versi ini memisahkan kode dan nama proyek, dan baris lama diisi ulang dari
`raw_payload` yang tersimpan. Yang disentuh hanya baris yang kolomnya masih
berbentuk repr (diawali `{`): nama proyek yang sudah disunting orang tidak boleh
tertimpa, dan baris yang ditarik lagi akan diperbarui sendiri oleh
`_upsert_rows`. Baris rusak yang payload-nya tidak memuat proyek dikosongkan,
bukan dibiarkan menampilkan repr.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    model = env['presenly.saas.attendance.log'].sudo()

    diperbaiki = 0
    dikosongkan = 0
    for company in env['res.company'].sudo().search([]):
        baris_diperbaiki, baris_dikosongkan = model._repair_project_columns(company)
        diperbaiki += baris_diperbaiki
        dikosongkan += baris_dikosongkan

    _logger.info(
        'presenly_saas 19.0.2.5.0: %s baris presensi kolom proyeknya '
        'diperbaiki, %s dikosongkan karena payload-nya tidak memuat proyek.',
        diperbaiki, dikosongkan,
    )
