"""Isi kolom perusahaan cabang pada baris pengajuan yang sudah ada.

Versi 19.0.2.3.0 mengisi id lokasi dan nama cabangnya. Versi ini menambah
`tenant_client_company_id`, yaitu perusahaan Odoo dari cabang itu, karena
aturan pemisahan membandingkan **perusahaan** yang diizinkan pengguna, bukan
id klien: dua tenant bisa punya id klien yang sama, dan membandingkan id klien
akan membuat keduanya saling melihat.

Pengisiannya memakai helper yang sama dengan penarikan, jadi kolom yang sudah
terisi tidak ditulis ulang.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODELS = (
    'presenly.saas.leave',
    'presenly.saas.overtime',
    'presenly.saas.medical.certificate',
)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    perusahaan = env['res.company'].sudo().search([])
    diisi = 0
    for model_name in MODELS:
        model = env[model_name]
        for company in perusahaan:
            diisi += model._mirror_fill_branches(company)

    _logger.info(
        'presenly_saas 19.0.2.4.0: %s baris pengajuan diisi perusahaan '
        'cabangnya.', diisi,
    )
