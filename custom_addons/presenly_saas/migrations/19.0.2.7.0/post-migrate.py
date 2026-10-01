"""Buang kolom proyek yang ternyata tidak dipakai.

Versi 19.0.2.6.0 menambahkan `project_external_id` dan relasi `project_id` ke
cermin proyek pada log presensi. Setelah dipakai, keduanya tidak diperlukan:
kode dan nama proyeknya sudah tersimpan di barisnya sendiri, dan menampilkan
relasinya hanya menggandakan kolom yang sama. Migrasi versi itu dihapus, dan
kolomnya dibuang di sini supaya tidak tertinggal sebagai kolom mati.

Odoo tidak membuang kolom saat field-nya dihapus dari model, jadi pembersihan
ini memang harus dikerjakan di sini. Dijalankan hanya bila kolomnya ada, supaya
basis yang belum pernah menjalankan 19.0.2.6.0 tidak gagal.
"""

import logging

_logger = logging.getLogger(__name__)

KOLOM = ('project_external_id', 'project_id')


def migrate(cr, version):
    if not version:
        return

    cr.execute("SELECT to_regclass('presenly_saas_attendance_log')")
    if not cr.fetchone()[0]:
        return

    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'presenly_saas_attendance_log'
          AND column_name IN %s
    """, (KOLOM,))
    ada = [row[0] for row in cr.fetchall()]
    if not ada:
        return

    for kolom in ada:
        # Nama kolomnya berasal dari daftar tetap di berkas ini, bukan dari
        # masukan pengguna, jadi aman dirangkai ke perintahnya.
        cr.execute('ALTER TABLE presenly_saas_attendance_log DROP COLUMN "%s"' % kolom)

    _logger.info(
        'presenly_saas 19.0.2.7.0: kolom proyek yang tidak dipakai dibuang: %s.',
        ', '.join(sorted(ada)),
    )
