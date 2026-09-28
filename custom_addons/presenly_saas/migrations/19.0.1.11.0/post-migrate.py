"""Nyalakan penyegaran otomatis pada instalasi yang sudah ada.

Kolom `request_sync_minutes` ditambahkan di 19.0.1.9.0 dengan nilai bawaan 5
menit, tetapi Odoo hanya menerapkan nilai bawaan itu pada instalasi baru. Baris
konfigurasi yang sudah ada mendapat 0 — dan 0 berarti penyegaran otomatis
dimatikan. Akibatnya fitur itu tidak pernah berjalan pada instalasi yang sudah
terpasang, tanpa satu pun pesan kesalahan.

Sebelum 19.0.1.9.0 kolom itu belum ada, jadi 0 pada database yang baru dinaikkan
bukan pilihan pengguna: tidak ada antarmuka yang bisa memilihnya. Karena itu
nilainya dinaikkan ke 5.

Siapa pun yang memang ingin mematikannya tinggal mengubahnya kembali menjadi 0
di halaman Settings setelah ini.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

DEFAULT_MINUTES = 5


def migrate(cr, version):
    if not version:
        # Instalasi baru: nilai bawaannya sudah benar.
        return

    cr.execute(
        """
        UPDATE presenly_saas_config
           SET request_sync_minutes = %s
         WHERE request_sync_minutes IS NULL OR request_sync_minutes = 0
        """,
        [DEFAULT_MINUTES],
    )
    _logger.info(
        'presenly_saas 19.0.1.11.0: penyegaran otomatis dinyalakan pada %d baris '
        'konfigurasi (%s menit).', cr.rowcount, DEFAULT_MINUTES,
    )
