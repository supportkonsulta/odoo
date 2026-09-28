"""Bersihkan sisa aksi server dari cron yang sudah diganti nama.

Versi 19.0.1.10.0 menghapus record cron lamanya, tetapi Odoo membuat **dua**
record untuk satu cron: baris cronnya sendiri, dan baris aksi server yang
ditumpangi lewat `_inherits`. Menghapus baris cronnya tidak ikut menghapus baris
aksinya, sehingga xmlid aksi itu tertinggal sebagai penunjuk ke record yang tidak
dipakai siapa pun lagi.

Tidak berbahaya, tetapi mengotori daftar xmlid dan membuat pertanyaan "cron yang
mana yang benar-benar berjalan" sulit dijawab dari database.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

OBSOLETE_XMLID = (
    'presenly_saas.ir_cron_presenly_saas_sync_requests_ir_actions_server'
)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    module, name = OBSOLETE_XMLID.split('.', 1)
    data = env['ir.model.data'].sudo().search(
        [('module', '=', module), ('name', '=', name)], limit=1
    )
    if not data:
        return

    record = env[data.model].sudo().browse(data.res_id)
    if record.exists():
        record.unlink()
    else:
        data.unlink()
    _logger.info(
        'presenly_saas 19.0.1.10.1: sisa aksi server dari cron lama dibersihkan.'
    )
