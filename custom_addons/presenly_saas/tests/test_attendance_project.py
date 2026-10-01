"""Kolom proyek pada cermin presensi: dari objek API menjadi kode dan nama.

Sampai versi sebelumnya `employee.project` - sebuah objek - diserahkan apa adanya
ke kolom `Char`, sehingga yang tampil di form Detail Data Presensi adalah repr
JSON-nya. Berkas ini menjaga empat hal yang mudah rusak tanpa terlihat:

1. pemetaannya memisahkan kode dan nama, bukan menyimpan objeknya;
2. proyek yang datang bukan sebagai objek tidak disimpan sebagai teks mentah;
3. labelnya satu kolom, `[KODE] Nama`;
4. baris lama benar-benar diperbaiki, dan yang sudah bersih tidak tersentuh.
"""

from odoo.tests import TransactionCase, tagged


def attendance_row(**overrides):
    row = {
        'id': 7001,
        'work_date': '2026-09-21',
        'user_id': 2,
        'status': 'closed',
        'employee': {
            'id': 2,
            'nopeg': 'iksg-rangga',
            'name': 'rangga',
            'project': {
                'id': 3,
                'project_code': '987364',
                'project_name': 'MAMBU KECUT',
                'client': {'id': 1, 'name': 'CLIENT 1'},
            },
        },
        'location': {'id': 501, 'name': 'PT KONSULTA'},
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlyAttendanceProject(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Log = cls.env['presenly.saas.attendance.log']

    def setUp(self):
        super().setUp()
        self.Log.search([]).unlink()

    def _baris(self, **overrides):
        values = self.Log._values_from_payload(
            self.company, attendance_row(**overrides),
        )
        self.assertTrue(values, 'payload uji ditolak, tesnya tidak bermakna')
        return self.Log.create(values)

    def _baris_rusak(self, payload, nama="{'id': 3, 'project_name': 'MAMBU'}"):
        """Baris seperti yang ditinggalkan versi sebelumnya."""
        return self.Log.create({
            'external_id': 7002,
            'work_date': '2026-09-21',
            'employee_name': 'rangga',
            'project_name': nama,
            'company_id': self.company.id,
            'raw_payload': payload,
        })

    # ------------------------------------------------------------------
    # Pemetaan
    # ------------------------------------------------------------------
    def test_proyek_dipisah_menjadi_kode_dan_nama(self):
        baris = self._baris()

        self.assertEqual(baris.project_code, '987364')
        self.assertEqual(baris.project_name, 'MAMBU KECUT')
        self.assertNotIn(
            '{', baris.project_name,
            'repr payload tidak boleh tersimpan di kolom nama proyek',
        )

    def test_label_proyek_satu_kolom(self):
        self.assertEqual(self._baris().project_label, '[987364] MAMBU KECUT')

    def test_proyek_berbentuk_string_tidak_disimpan(self):
        """Payload boleh berbentuk lain; yang salah bukan alasan menyimpan teksnya."""
        baris = self._baris(employee={
            'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga',
            'project': "{'id': 3, 'project_name': 'MAMBU'}",
        })

        self.assertFalse(baris.project_name)
        self.assertFalse(baris.project_code)
        self.assertFalse(baris.project_label)

    def test_tanpa_proyek_kolomnya_kosong(self):
        baris = self._baris(employee={'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'})

        self.assertFalse(baris.project_name)
        self.assertFalse(baris.project_label)

    def test_proyek_lokasi_yang_memakai_name_tetap_terbaca(self):
        """Resource lain menyebut namanya `name`, bukan `project_name`."""
        baris = self._baris(employee={
            'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga',
            'project': {'id': 4, 'name': 'MAMBU ASEM'},
        })

        self.assertEqual(baris.project_name, 'MAMBU ASEM')
        self.assertEqual(baris.project_label, 'MAMBU ASEM')

    # ------------------------------------------------------------------
    # Perbaikan baris lama (migrasi 19.0.2.5.0)
    # ------------------------------------------------------------------
    def test_baris_lama_diperbaiki_dari_payload(self):
        baris = self._baris_rusak({
            'id': 7002,
            'employee': {'id': 2, 'project': {'id': 3, 'project_code': '987364',
                                              'project_name': 'MAMBU KECUT'}},
        })

        self.assertEqual(self.Log._repair_project_columns(self.company), (1, 0))
        self.assertEqual(baris.project_code, '987364')
        self.assertEqual(baris.project_name, 'MAMBU KECUT')

    def test_baris_rusak_tanpa_proyek_dikosongkan(self):
        """Repr di layar lebih buruk daripada kolom kosong."""
        baris = self._baris_rusak({'id': 7002, 'employee': {'id': 2}})

        self.assertEqual(self.Log._repair_project_columns(self.company), (0, 1))
        self.assertFalse(baris.project_name)

    def test_nama_proyek_yang_sudah_bersih_tidak_ditimpa(self):
        baris = self.Log.create({
            'external_id': 7003,
            'work_date': '2026-09-21',
            'project_code': '111',
            'project_name': 'Nama yang Disunting Orang',
            'company_id': self.company.id,
            'raw_payload': {'id': 7003, 'employee': {'project': {
                'project_code': '999', 'project_name': 'Nama dari Payload'}}},
        })

        self.assertEqual(self.Log._repair_project_columns(self.company), (0, 0))
        self.assertEqual(baris.project_name, 'Nama yang Disunting Orang')
        self.assertEqual(baris.project_code, '111')

    def test_perbaikan_dijalankan_dua_kali_hasilnya_sama(self):
        self._baris_rusak({
            'id': 7002,
            'employee': {'id': 2, 'project': {'id': 3, 'project_code': '987364',
                                              'project_name': 'MAMBU KECUT'}},
        })

        self.assertEqual(self.Log._repair_project_columns(self.company), (1, 0))
        self.assertEqual(
            self.Log._repair_project_columns(self.company), (0, 0),
            'perbaikan kedua tidak boleh mengubah apa pun lagi',
        )
