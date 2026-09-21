import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Record yang dibuat versi 19.0.1.0.0 dan sudah tidak dipakai lagi setelah
# konfigurasi pindah ke halaman Settings native.
#
# Odoo tidak menghapus record yang dihilangkan dari XML, dan record ini dibuat
# dengan `noupdate=1`, jadi tanpa migration keduanya akan tetap tertinggal dan
# halaman Konfigurasi lama masih bisa dibuka. Itu justru membuat dua tempat
# mengubah data yang sama, yang ingin dihilangkan.
OBSOLETE_XMLIDS = (
    # Anak menu: "Presenly SaaS > Configuration > Presenly SaaS Connection".
    'presenly_saas.menu_presenly_saas_config',
    # Server action yang membuka form koneksi dari menu tersebut.
    'presenly_saas.action_presenly_saas_open_config',
)

# CATATAN (19.0.1.2.0): `presenly_saas.menu_presenly_saas_configuration`
# SEMPAT ada di daftar di atas, lalu dikeluarkan ketika menu Configuration
# dipakai kembali sebagai induk dari pintasan "Settings".
#
# Alasannya: post-migrate berjalan SETELAH data modul dimuat. Kalau xmlid itu
# tetap dihapus di sini, database yang naik langsung dari 19.0.1.0.0 ke
# 19.0.1.2.0 akan membuat menu Configuration yang baru, lalu langsung
# menghapusnya di langkah berikutnya.


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
        # Baris ir_model_data yang menggantung tanpa record.
        data.unlink()
    return True


def migrate(cr, version):
    if not version:
        # Instalasi baru: menu lama tidak pernah ada.
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    removed = [xmlid for xmlid in OBSOLETE_XMLIDS if _drop_xmlid(env, xmlid)]

    if removed:
        _logger.info(
            'presenly_saas 19.0.1.1.0: konfigurasi dipindah ke halaman Settings '
            'native; %d record lama dihapus: %s',
            len(removed),
            ', '.join(removed),
        )
    else:
        _logger.info(
            'presenly_saas 19.0.1.1.0: tidak ada record konfigurasi lama yang perlu dihapus.'
        )
