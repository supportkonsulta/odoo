"""Lampiran saat barisnya dihapus dari Presenly.

`presenly_saas_mirror_mixin.unlink` pernah memanggil `unlink` pada lampiran
yang **sudah** dibuang Odoo — `BaseModel.unlink` membuang `ir.attachment` yang
`res_model`/`res_id`-nya menunjuk baris yang dihapus. Panggilan kedua itu
melempar `MissingError`, dan galat itu membatalkan seluruh penarikan: data yang
sudah dihapus di Presenly tidak pernah ikut terhapus di Odoo, dan tombol tarik
manual gagal dengan pesan yang tidak menyebut sebabnya.

Tes di sini menjaga sifat itu: menghapus baris cermin berhasil walaupun
lampirannya sudah hilang lebih dulu.
"""

from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


def leave_row(**overrides):
    row = {
        'id': 11,
        'reference_number': 'CT/2026/00001',
        'leave_date': '2026-09-21',
        'start_date': '2026-09-22',
        'end_date': '2026-09-24',
        'total_days': 3.0,
        'status': 'approved',
        'certificate_file': '/uploads/leaves/surat.pdf',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
    }
    row.update(overrides)
    return row


def timesheet_row(**overrides):
    row = {
        'id': 31,
        'date': '2026-09-21',
        'photo_file': '/uploads/timesheets/foto.jpg',
        'status': 'approved',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'project': {'id': 7, 'code': 'PRJ-001', 'name': 'Pendampingan IKM'},
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlyAttachmentUnlink(TransactionCase):
    """Baris yang hilang di Presenly terhapus, lampirannya tidak menghalangi."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Attachment = cls.env['ir.attachment']
        cls.Sync = cls.env['presenly.saas.attachment.sync']

    def setUp(self):
        super().setUp()
        for model_name in ('presenly.saas.leave', 'presenly.saas.timesheet'):
            self.env[model_name].search([]).unlink()

    def _tarik(self, model_name, rows):
        return self.env[model_name]._mirror_replace_range(
            self.company, rows, date(2026, 9, 1), date(2026, 9, 30),
        )

    def _pasang_lampiran(self, model_name, rows):
        return self.Sync.sync_attachments(
            self.company, model_name, rows, lambda _path: b'isi berkas uji',
        )

    def _lampiran(self, model_name):
        return self.Attachment.search([('res_model', '=', model_name)])

    def _skenario(self, model_name, rows):
        self._tarik(model_name, rows)
        self._pasang_lampiran(model_name, rows)

        cermin = self.env[model_name]
        self.assertEqual(cermin.search_count([]), len(rows))
        lampiran = self._lampiran(model_name)
        self.assertEqual(len(lampiran), len(rows))

        # Presenly menghapus satu baris, lalu sisa rentangnya diganti tanpa baris
        # itu — inilah langkah yang dulu melempar MissingError.
        self._tarik(model_name, rows[:1])

        self.assertEqual(cermin.search([]).external_id, rows[0]['id'])
        self.assertFalse(
            self._lampiran(model_name).exists(),
            'lampiran baris yang hilang ikut dibuang, bukan menghalangi',
        )

    def test_baris_cuti_yang_hilang(self):
        self._skenario('presenly.saas.leave', [
            leave_row(id=11),
            leave_row(id=12, reference_number='CT/2026/00002',
                      certificate_file='/uploads/leaves/dua.pdf'),
        ])

    def test_baris_timesheet_yang_hilang(self):
        self._skenario('presenly.saas.timesheet', [
            timesheet_row(id=31),
            timesheet_row(id=32, photo_file='/uploads/timesheets/dua.jpg'),
        ])

    def test_seluruh_rentang_diganti_dengan_kosong(self):
        """Bulan yang tidak lagi punya pengajuan sama sekali."""
        rows = [leave_row(id=11), leave_row(id=12, reference_number='CT/2026/00002')]
        self._tarik('presenly.saas.leave', rows)
        self._pasang_lampiran('presenly.saas.leave', rows)

        self.assertEqual(self._tarik('presenly.saas.leave', []), 0)

        self.assertFalse(self.env['presenly.saas.leave'].search([]))
        self.assertFalse(self._lampiran('presenly.saas.leave').exists())
