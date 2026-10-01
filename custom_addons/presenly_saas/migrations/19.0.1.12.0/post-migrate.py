"""Betulkan nilai penyegaran otomatis, dan pasang irama cron.

Dua hal yang diperbaiki di sini.

**Ambang penyegaran.** Kolom `request_sync_minutes` ditambahkan di 19.0.1.9.0
dengan bawaan 5 menit, dan nilai bawaan itu tidak berlaku untuk baris
konfigurasi yang sudah ada — yang didapat 0, dan 0 berarti mati. Migrasi
19.0.1.11.0 sudah menaikkannya ke 5, tetapi 5 hanya bertahan sampai halaman
Settings disimpan sekali: compute halaman itu belum mengisi fieldnya, sehingga
yang tertulis kembali adalah 0. Compute-nya sudah diperbaiki, dan di sini
nilainya disetel ke 1 menit — cukup segar untuk terasa langsung, dan masih
menahan diri dari menarik ulang pada setiap gulir dan pencarian.

Nilai 0 pada database yang naik bukan pilihan yang mungkin diambil pengguna
sebelum kolomnya ada. Siapa pun yang memang ingin mematikannya tinggal
mengubahnya menjadi 0 di halaman Settings setelah ini.

**Irama cron.** Kolom `cron_sync_minutes` baru, dan 0 berarti cron-nya
dimatikan. Bawaannya 15 menit, dan itu berlaku untuk instalasi baru; baris yang
sudah ada diisi 15 di sini.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

REFRESH_MINUTES = 1
CRON_MINUTES = 15


def migrate(cr, version):
    if not version:
        # Instalasi baru: nilai bawaannya sudah benar.
        return

    cr.execute(
        """
        UPDATE presenly_saas_config
           SET request_sync_minutes = %s
         WHERE request_sync_minutes IS NULL OR request_sync_minutes IN (0, 5)
        """,
        [REFRESH_MINUTES],
    )
    _logger.info(
        'presenly_saas 19.0.1.12.0: ambang penyegaran disetel %s menit pada %d '
        'baris konfigurasi.', REFRESH_MINUTES, cr.rowcount,
    )

    cr.execute(
        """
        UPDATE presenly_saas_config
           SET cron_sync_minutes = %s
         WHERE cron_sync_minutes IS NULL OR cron_sync_minutes = 0
        """,
        [CRON_MINUTES],
    )
    _logger.info(
        'presenly_saas 19.0.1.12.0: irama cron diisi %s menit pada %d baris '
        'konfigurasi.', CRON_MINUTES, cr.rowcount,
    )
