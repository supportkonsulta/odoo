"""Buang sisa cermin rekap presensi yang sudah dihapus.

Modelnya dihapus dari kode, bukan dimatikan. Odoo membersihkan sendiri data
model, view, action, dan menunya saat upgrade, tetapi **tabelnya** tidak ikut
dibuang — tanpa langkah ini ia tertinggal sebagai tabel yatim yang tidak ada
yang membacanya lagi.

Ditulis sebagai SQL langsung karena modelnya sudah tidak ada di registry.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Instalasi baru: tabelnya belum pernah dibuat.
        return

    cr.execute("SELECT to_regclass('presenly_saas_attendance_recap')")
    if not cr.fetchone()[0]:
        return

    cr.execute('DROP TABLE presenly_saas_attendance_recap CASCADE')
    _logger.info(
        'presenly_saas 19.0.2.2.0: tabel rekap presensi yang sudah dihapus '
        'ikut dibuang.',
    )
