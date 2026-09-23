"""Ganti nama cron penarikan tambahan.

Versi 19.0.1.10.0 memperluas cron itu: dulu hanya pengajuan, sekarang juga
penyeragaman timesheet dan log presensi. Nama record-nya karena itu diganti dari
`ir_cron_presenly_saas_sync_requests` menjadi `ir_cron_presenly_saas_sync_recent`,
supaya tidak ada catatan yang berbohong tentang isinya.

Record cron dibuat dengan `noupdate="1"`, jadi Odoo tidak menghapusnya sendiri
ketika xmlid-nya hilang dari XML. Tanpa pembersihan ini, database yang sudah
terpasang akan menjalankan **dua** cron untuk pekerjaan yang sama: yang lama
dengan xmlid lama, dan yang baru. Pekerjaannya idempoten, jadi akibatnya bukan
data ganda, melainkan panggilan API dua kali lipat.

Aman diulang: penghapusan xmlid memeriksa keberadaannya lebih dulu.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Odoo membuat dua record untuk satu cron: barisnya sendiri, dan baris aksi
# server yang ditumpangi lewat `_inherits`. Keduanya punya xmlid sendiri, jadi
# keduanya harus dibersihkan — menghapus baris cronnya saja meninggalkan xmlid
# aksi yang menggantung.
OBSOLETE_XMLIDS = (
    'presenly_saas.ir_cron_presenly_saas_sync_requests',
    'presenly_saas.ir_cron_presenly_saas_sync_requests_ir_actions_server',
)


def migrate(cr, version):
    if not version:
        # Instalasi baru: xmlid lama tidak pernah ada.
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    dihapus = []
    for xmlid in OBSOLETE_XMLIDS:
        module, name = xmlid.split('.', 1)
        data = env['ir.model.data'].sudo().search(
            [('module', '=', module), ('name', '=', name)], limit=1
        )
        if not data:
            continue
        record = env[data.model].sudo().browse(data.res_id)
        if record.exists():
            record.unlink()
        else:
            # Record-nya sudah hilang lewat cascade; yang tersisa hanya penandanya.
            data.unlink()
        dihapus.append(xmlid)

    _logger.info(
        'presenly_saas 19.0.1.10.0: cron penarikan tambahan diganti nama; '
        '%d record lama dibersihkan.', len(dihapus),
    )
