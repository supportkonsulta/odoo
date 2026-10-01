"""Cermin pengajuan menyiapkan empat kunci yang dipakai payroll.

Payroll menyaring lembur dengan empat kunci, dan itu terbaca di
`presenly_payroll/models/custom_payroll_slip.py`:

    employee_id (hr.employee), state = approved, rentang date,
    work_location_id (hr.work.location)

Tes ini membuktikan keempatnya **bisa dijawab cermin lembur** dengan arti yang
sama, sehingga penyambungan payroll nanti hanya perlu mengganti nama model dan
satu baris domain. Yang tidak diuji di sini, karena memang tidak dikerjakan:
modul payrollnya sendiri.
"""

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


def overtime_row(**overrides):
    row = {
        'id': 7001,
        'overtime_date': '2026-09-21',
        'purpose': 'Penutupan bulan',
        'start_time': '17:00:00',
        'end_time': '19:00:00',
        'total_hours': 2.0,
        'day_type': 'workday',
        'within_radius': True,
        'overtime_pay': 150000.0,
        'approval_status': 'approved',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'location': {'id': 501, 'name': 'Lokasi Uji'},
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlyOvertimePayrollReady(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Overtime = cls.env['presenly.saas.overtime']
        cls.Mirror = cls.env['presenly.saas.employee']
        cls.Location = cls.env['presenly.saas.work.location']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)

    def setUp(self):
        super().setUp()
        self.Overtime.search([]).unlink()
        self.Location.search([]).unlink()
        self.Mirror.search([]).unlink()

        # Cabang, beserta lokasi kerjanya: di Presenly maupun yang native.
        self.cabang = self.env['res.company'].create({
            'name': 'CLIENT UJI', 'presenly_client_id': 91,
        })
        self.alamat = self.env['res.partner'].create({'name': 'Lokasi Uji'})
        self.lokasi_native = self.env['hr.work.location'].create({
            'name': 'Lokasi Uji',
            'address_id': self.alamat.id,
            'company_id': self.cabang.id,
            'presenly_external_id': 501,
        })
        self.Location.create({
            'external_id': 501,
            'name': 'Lokasi Uji',
            'company_id': self.company.id,
            'internal_company_id': 91,
            'internal_company_name': 'CLIENT UJI',
        })

        # Pegawai: cermin, dan `hr.employee` yang tertaut.
        self.hr = self.Hr.create({
            'name': 'Pegawai Uji',
            'presenly_nopeg': 'iksg-rangga',
        })
        self.cermin = self.Mirror.create({
            'external_id': 5001,
            'nopeg': 'iksg-rangga',
            'name': 'Pegawai Uji',
            'company_id': self.company.id,
            'hr_employee_id': self.hr.id,
        })

    def _tarik(self, baris):
        self.Overtime._mirror_upsert(self.company, baris)
        return self.Overtime.search([('external_id', '=', baris[0]['id'])])

    # ------------------------------------------------------------------
    # Empat kunci payroll
    # ------------------------------------------------------------------
    def test_empat_kunci_payroll_bisa_dijawab(self):
        baris = self._tarik([overtime_row()])

        self.assertEqual(baris.hr_employee_id, self.hr, 'kunci pegawai')
        self.assertEqual(baris.status, 'approved', 'kunci status')
        self.assertEqual(baris.overtime_date, fields.Date.to_date('2026-09-21'), 'kunci tanggal')
        self.assertEqual(
            baris.hr_work_location_id, self.lokasi_native, 'kunci lokasi kerja',
        )

        # Persis domain yang dipakai payroll, dijalankan pada cermin.
        hasil = self.Overtime.search([
            ('hr_employee_id', '=', self.hr.id),
            ('status', '=', 'approved'),
            ('overtime_date', '>=', '2026-09-01'),
            ('overtime_date', '<=', '2026-09-30'),
            ('hr_work_location_id', '=', self.lokasi_native.id),
        ])
        self.assertEqual(hasil, baris, 'domain payroll menemukan barisnya')

    def test_cabang_pembayarnya_ikut_tercatat(self):
        baris = self._tarik([overtime_row()])

        self.assertEqual(baris.tenant_client_id, 91)
        self.assertEqual(baris.tenant_client_name, 'CLIENT UJI')
        self.assertEqual(
            baris.tenant_client_company_id, self.cabang,
            'perusahaan pembayar, dipakai menyaring per perusahaan',
        )
        self.assertEqual(baris.tenant_location_id.external_id, 501)

    def test_tautan_native_tidak_menunggu_cermin_lokasi(self):
        """Tautan lokasi native diisi dari id lokasinya, bukan dari cermin lokasi.

        Cermin lokasi bisa belum tersegarkan; `hr.work.location.presenly_external_id`
        sudah menyimpan id yang sama, jadi tautannya tidak perlu menunggunya.
        Yang tertinggal hanya cabangnya, dan itu memang tidak bisa diturunkan.
        """
        self.Location.search([]).unlink()

        baris = self._tarik([overtime_row()])

        self.assertEqual(baris.hr_employee_id, self.hr, 'tautan pegawai tetap ada')
        self.assertEqual(
            baris.hr_work_location_id, self.lokasi_native,
            'tautan lokasi memakai id lokasinya, bukan cermin lokasinya',
        )
        self.assertFalse(baris.tenant_client_name, 'cabangnya tidak bisa diturunkan')

    # ------------------------------------------------------------------
    # Klien dari payload
    # ------------------------------------------------------------------
    def test_klien_dari_payload_diutamakan(self):
        """Payload yang membawa kliennya lebih pasti daripada cermin lokasi.

        Cermin lokasinya di sini menyebut klien lain, dan payloadnya yang dipakai:
        itulah yang membuat cabangnya tidak bergantung pada kesegaran cermin
        lokasi.
        """
        self.cabang.write({'presenly_client_id': 91})
        self.Location.search([]).write({
            'internal_company_id': 77, 'internal_company_name': 'CLIENT LAMA',
        })
        cabang_payload = self.env['res.company'].create({
            'name': 'CLIENT BARU', 'presenly_client_id': 92,
        })

        baris = self._tarik([overtime_row(location={
            'id': 501,
            'name': 'Lokasi Uji',
            'internal_company': {'id': 92, 'name': 'CLIENT BARU'},
        })])

        self.assertEqual(baris.tenant_client_id, 92)
        self.assertEqual(baris.tenant_client_name, 'CLIENT BARU')
        self.assertEqual(baris.tenant_client_company_id, cabang_payload)

    def test_payload_tanpa_klien_tetap_diturunkan_dari_lokasi(self):
        """Baris lama, dan server yang belum mengirim kliennya."""
        baris = self._tarik([overtime_row()])

        self.assertEqual(baris.tenant_client_id, 91, 'dari cermin lokasinya')
