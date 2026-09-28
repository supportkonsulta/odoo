"""Segarkan pendaftaran webhook pada instalasi yang sudah berjalan.

Versi ini mulai menangani peristiwa jadwal kerja
(`weekly_schedule.created`/`updated`), sedangkan pendaftaran yang sudah ada
menyimpan daftar peristiwa yang lama. Server tidak menambahkannya sendiri, jadi
perubahan jadwal kerja di aplikasi tidak pernah sampai ke Odoo — dan tidak ada
galat yang terlihat di kedua sisi.

Pemeriksaan yang sama juga dijalankan `_pull_employees` setiap kali pegawai
ditarik, sehingga penambahan peristiwa berikutnya tidak perlu migrasi lagi.
Yang ini ada supaya instalasi yang sudah berjalan tidak perlu menunggu tarikan
berikutnya.

Kegagalan di sini **tidak** menggagalkan upgrade. Servernya bisa sedang tidak
terjangkau, dan itu bukan alasan menolak versi baru; pemeriksaan berikutnya akan
mencobanya lagi. Batas waktunya dipendekkan karena tidak ada yang menunggu
jawabannya.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5


def migrate(cr, version):
    if not version:
        # Instalasi baru: belum ada pendaftaran untuk disegarkan.
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    configs = env['presenly.saas.config'].search([
        ('enabled', '=', True),
        ('webhook_enabled', '=', True),
        ('webhook_url', '!=', False),
    ])

    disegarkan = 0
    for config in configs:
        try:
            if config.ensure_webhook_registration(timeout=TIMEOUT_SECONDS):
                disegarkan += 1
        except Exception as exc:  # noqa: BLE001 - upgrade tidak boleh gagal karena ini
            _logger.warning(
                'presenly_saas_hr 19.0.1.1.0: pendaftaran webhook untuk %s '
                'tidak bisa diperiksa: %s',
                config.company_id.display_name, exc,
            )

    if disegarkan:
        _logger.info(
            'presenly_saas_hr 19.0.1.1.0: pendaftaran webhook disegarkan untuk '
            '%d koneksi.', disegarkan,
        )
