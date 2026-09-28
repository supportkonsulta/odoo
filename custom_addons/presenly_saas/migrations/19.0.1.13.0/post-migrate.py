"""Nyalakan penyegaran saat halaman dibuka pada instalasi yang sudah ada.

`request_sync_minutes` diganti `request_auto_refresh`: yang dibutuhkan bukan
ambang waktu, melainkan pemeriksaan murah "ada yang berubah?" setiap kali
halaman cermin dibuka. Satu permintaan ke API, lalu yang berubah saja yang
ditarik — jadi tidak ada lagi alasan untuk menahan pemeriksaannya.

Kolom baru mendapat nilai bawaannya hanya pada instalasi baru, jadi baris
konfigurasi yang sudah ada dinyalakan di sini.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Instalasi baru: nilai bawaannya sudah benar.
        return

    cr.execute(
        """
        UPDATE presenly_saas_config
           SET request_auto_refresh = TRUE
         WHERE request_auto_refresh IS NULL
        """,
    )
    _logger.info(
        'presenly_saas 19.0.1.13.0: penyegaran saat halaman dibuka dinyalakan '
        'pada %d baris konfigurasi.', cr.rowcount,
    )
