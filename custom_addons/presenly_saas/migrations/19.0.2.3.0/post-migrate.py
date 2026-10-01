"""Isi cabang baris pengajuan yang sudah ada, dari payload yang tersimpan.

Kolom `location_id`, `tenant_client_id`, dan `tenant_client_name` baru ada di
versi ini. Baris yang ditarik sebelum versi ini tidak punya ketiganya, padahal
id lokasinya **ada** di `raw_payload` yang memang disimpan utuh. Jadi
pengisiannya tidak perlu memanggil API sama sekali.

Cabangnya tidak diambil dari payload (payload pengajuan tidak membawa klien),
melainkan diturunkan dari lokasi kerja. Keduanya dikerjakan helper di
`presenly.saas.mirror.mixin`, sehingga migrasi ini tidak menyimpan logikanya
sendiri dan bisa diuji lewat helper itu.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Hanya jenis yang payloadnya membawa `location`. Dua sisanya (koreksi presensi
# dan tukar shift) tidak membawa lokasi sama sekali, jadi tidak ada yang bisa
# diisi; keduanya dibiarkan apa adanya, bukan ditebak.
MODELS = (
    'presenly.saas.leave',
    'presenly.saas.overtime',
    'presenly.saas.medical.certificate',
)


def migrate(cr, version):
    if not version:
        # Instalasi baru: tidak ada baris lama yang perlu diisi.
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    perusahaan = env['res.company'].sudo().search([])
    id_lokasi = 0
    bercabang = 0
    for model_name in MODELS:
        model = env[model_name]
        for company in perusahaan:
            id_lokasi += model._mirror_fill_location_ids_from_payload(company)
            bercabang += model._mirror_fill_branches(company)

    _logger.info(
        'presenly_saas 19.0.2.3.0: %s baris pengajuan diisi id lokasinya, '
        '%s di antaranya mendapat cabangnya.', id_lokasi, bercabang,
    )
