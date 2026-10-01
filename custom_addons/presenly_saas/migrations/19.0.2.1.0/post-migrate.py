"""Buang sisa layar rekonsiliasi yang sudah dihapus.

Layarnya dihapus dari kode, bukan dimatikan: modelnya, viewnya, actionnya, dan
menunya tidak ada lagi di manifest. Odoo membersihkan sendiri data itu saat
upgrade — ir.model, ir.model.data, view, action, dan menu-nya benar-benar
hilang — tetapi **tabel** modelnya tidak ikut dibuang. Tanpa langkah ini ia
tertinggal sebagai tabel yatim yang tidak ada yang membacanya lagi, dan tetap
tampak oleh siapa pun yang memeriksa daftar tabel.

Ditulis sebagai SQL langsung karena modelnya sudah tidak ada lagi di registry;
tidak ada ORM yang bisa dipakai untuk menghapusnya.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Instalasi baru: tabelnya belum pernah dibuat.
        return

    # Diperiksa dulu, bukan mengandalkan jumlah baris `DROP TABLE`: DDL tidak
    # melaporkan berapa yang terbuang, jadi catatannya akan selalu salah.
    cr.execute("SELECT to_regclass('presenly_saas_reconciliation')")
    if not cr.fetchone()[0]:
        return

    cr.execute('DROP TABLE presenly_saas_reconciliation CASCADE')
    _logger.info(
        'presenly_saas 19.0.2.1.0: tabel layar rekonsiliasi yang sudah '
        'dihapus ikut dibuang.',
    )
