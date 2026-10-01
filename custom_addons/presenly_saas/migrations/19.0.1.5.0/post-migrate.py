"""Bersihkan sisa katalog fitur eksternal.

Versi 19.0.1.5.0 menghapus menu "Presenly Features" beserta modelnya. Menu itu
menampilkan katalog endpoint yang disediakan server, dan tidak ada satu pun
tombol atau menu yang memicu penarikannya — jadi isinya selalu kosong, sementara
`presenly.saas.guard.has_feature()` (yang mengatur hak paket) bekerja dari data
langganan, bukan dari katalog ini.

Dua hal yang tertinggal setelah modelnya dihapus, dan keduanya dibersihkan di
sini:

1. **Record Odoo-nya.** Odoo menyimpan record yang dihilangkan dari XML. Menu,
   aksi, dan dua view-nya tetap ada di database kalau tidak dihapus, dan menu
   yang tidak punya model akan gagal saat diklik.
2. **Tabelnya.** Kolom-kolomnya tidak ikut terhapus bersama modelnya. Isinya
   hanya cermin katalog dari server, jadi tidak ada data yang hilang yang tidak
   bisa ditarik ulang.

Aman diulang: penghapusan xmlid memeriksa keberadaannya lebih dulu, dan
`DROP TABLE` memakai `IF EXISTS`.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

OBSOLETE_XMLIDS = (
    # Anak menu "Presenly SaaS > Presenly Features".
    'presenly_saas.menu_presenly_saas_external_feature',
    # Aksi yang membukanya.
    'presenly_saas.action_presenly_saas_external_feature',
    # Dua view katalognya.
    'presenly_saas.view_presenly_saas_external_feature_list',
    'presenly_saas.view_presenly_saas_external_feature_search',
)

# Tabel model yang dihapus. Ditulis apa adanya karena tidak ada lagi model yang
# bisa ditanyakan namanya.
OBSOLETE_TABLE = 'presenly_saas_external_feature'


def _drop_xmlid(env, xmlid):
    """Hapus record beserta ir_model_data-nya. Aman bila sudah tidak ada."""
    module, name = xmlid.split('.', 1)
    data = env['ir.model.data'].sudo().search(
        [('module', '=', module), ('name', '=', name)], limit=1
    )
    if not data:
        return False

    record = env[data.model].sudo().browse(data.res_id)
    if record.exists():
        record.unlink()
    else:
        # Record-nya sudah hilang; yang tersisa hanya penanda xmlid-nya.
        data.unlink()
    return True


def migrate(cr, version):
    if not version:
        # Instalasi baru: katalognya tidak pernah ada.
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    removed = [xmlid for xmlid in OBSOLETE_XMLIDS if _drop_xmlid(env, xmlid)]

    cr.execute('DROP TABLE IF EXISTS %s' % OBSOLETE_TABLE)

    _logger.info(
        'presenly_saas 19.0.1.5.0: katalog fitur eksternal dihapus; %d record '
        'lama dibersihkan dan tabel %s dibuang.',
        len(removed),
        OBSOLETE_TABLE,
    )
