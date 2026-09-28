"""Seragamkan status pengajuan yang sudah tercermin.

Cermin lembur menyimpan status di kolom `approval_status` dengan penanda lama
Presenly: `Y` (ya), `N` (tidak), `T` (tunggu). Kolom itu sekarang menjadi
`status` dengan kosakata modul ini, jadi isi lama dipetakan lebih dulu supaya
cermin tidak tampak kosong sampai penarikan berikutnya.

Empat jenis pengajuan lain sudah memakai kosakata yang sama. Isinya tetap
dilewatkan pemetaan yang sama supaya `status_raw` terisi dan nilai yang tidak
dikenal — misalnya `cancelled`, yang tidak ada di ENUM server — dikosongkan dari
`status` lalu disimpan apa adanya di `status_raw`, bukan ditampilkan sebagai
status yang salah.

Pemetaannya ditulis ulang di sini, bukan diimpor dari `STATUS_ALIASES`:
migration harus tetap berperilaku sama walau konstanta di kode berubah kemudian.
"""

import logging

_logger = logging.getLogger(__name__)

# `T` adalah "tunggu", bukan "tidak": pengajuan lembur dibuat dengan
# `approval_status = 'T'`, dan kode Presenly menyebut nilai itu "Pending".
OVERTIME_STATUS = {
    'y': 'approved',
    'n': 'rejected',
    't': 'pending',
}

# Empat jenis lain sudah memakai kosakata ini.
SUBMISSION_STATUS = {
    'pending': 'pending',
    'approved': 'approved',
    'rejected': 'rejected',
}

# (tabel, kolom sumber, pemetaan). Kolom sumber berbeda karena lembur memakai
# penamaan lamanya sendiri.
CITRA = (
    ('presenly_saas_overtime', 'approval_status', OVERTIME_STATUS),
    ('presenly_saas_leave', 'status', SUBMISSION_STATUS),
    ('presenly_saas_medical_certificate', 'status', SUBMISSION_STATUS),
    ('presenly_saas_attendance_correction', 'status', SUBMISSION_STATUS),
    ('presenly_saas_shift_swap', 'status', SUBMISSION_STATUS),
)


def _petakan(cr, table, sumber, mapping):
    """Isi `status` dan `status_raw` dari kolom status yang lama.

    Perbandingannya mengabaikan huruf besar-kecil, tetapi `status_raw` menyimpan
    nilai apa adanya: yang mengaudit perlu melihat yang benar-benar dikirim
    server, bukan versi yang sudah dirapikan migration.

    Nilai di luar `mapping` menghasilkan `status` kosong dengan nilai aslinya
    tetap tersimpan di `status_raw`.
    """
    klausa = ' '.join(
        "WHEN '%s' THEN '%s'" % (lama, baru) for lama, baru in mapping.items()
    )
    cr.execute(
        """
        UPDATE {table} AS cermin
           SET status_raw = asal.nilai,
               status = CASE LOWER(asal.nilai) {klausa} ELSE NULL END
          FROM (
              SELECT id, TRIM(CAST({sumber} AS TEXT)) AS nilai
                FROM {table}
          ) AS asal
         WHERE cermin.id = asal.id
           AND asal.nilai IS NOT NULL
           AND asal.nilai != ''
        """.format(table=table, sumber=sumber, klausa=klausa)
    )
    return cr.rowcount


def migrate(cr, version):
    if not version:
        # Instalasi baru: belum ada cermin lama yang perlu dipetakan.
        return

    hasil = []
    for table, sumber, mapping in CITRA:
        hasil.append('%s: %d baris' % (table, _petakan(cr, table, sumber, mapping)))

    _logger.info(
        'presenly_saas 19.0.1.4.0: status pengajuan diseragamkan (%s).',
        ', '.join(hasil),
    )
