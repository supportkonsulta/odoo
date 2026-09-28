from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.saas_client import PresenlySaasClient, SaasClientError

EMPTY_PAGE = {'data': [], 'meta': {'total': 0, 'total_pages': 0}}


def leave_row(**overrides):
    row = {
        'id': 11,
        'reference_number': 'CT/2026/00001',
        'leave_date': '2026-09-21',
        'start_date': '2026-09-22',
        'end_date': '2026-09-24',
        'total_days': 3.0,
        'purpose': 'Acara keluarga',
        'status': 'approved',
        'approved_at': '2026-09-20T08:00:00.000Z',
        'created_at': '2026-09-19T08:00:00.000Z',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'leave_type': {'id': 1, 'name': 'Cuti Tahunan'},
        'location': {'id': 2, 'name': 'Kantor Pusat'},
        'approver': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
    }
    row.update(overrides)
    return row


def overtime_row(**overrides):
    row = {
        'id': 21,
        'overtime_date': '2026-09-18',
        'purpose': 'Penutupan bulan',
        'start_time': '17:00:00',
        'end_time': '19:30:00',
        'total_hours': 2.5,
        'day_type': 'workday',
        'within_radius': True,
        'overtime_pay': 150000.0,
        'approval_status': 'approved',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'location': {'id': 2, 'name': 'Kantor Pusat'},
        'approver': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
    }
    row.update(overrides)
    return row


def medical_row(**overrides):
    row = {
        'id': 31,
        'dc_number': 'DC/2026/00001',
        'certificate_date': '2026-09-15',
        'start_date': '2026-09-15',
        'end_date': '2026-09-16',
        'reason': 'Demam',
        'status': 'approved',
        'employee': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
        'location': {'id': 2, 'name': 'Kantor Pusat'},
        'approver': None,
    }
    row.update(overrides)
    return row


def correction_row(**overrides):
    row = {
        'id': 41,
        'date': '2026-09-21',
        'requested_check_in_time': '2026-09-21T01:00:00.000Z',
        'requested_check_out_time': '2026-09-21T10:00:00.000Z',
        'original_check_in_time': '2026-09-21T01:25:00.000Z',
        'original_check_out_time': '2026-09-21T10:00:00.000Z',
        'reason': 'Lupa tap masuk',
        'status': 'approved',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'shift': {'id': 5, 'name': 'Normal 2'},
        'original_shift': {'id': 4, 'name': 'Normal'},
        'tl_approver': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
        'manager_approver': {'id': 4, 'nopeg': 'iksg-boss', 'name': 'boss'},
        'rejecter': None,
    }
    row.update(overrides)
    return row


def swap_row(**overrides):
    row = {
        'id': 51,
        'requester_date': '2026-09-21',
        'target_date': '2026-09-22',
        'reason': 'Ada urusan',
        'status': 'pending',
        'requester': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'target': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
        'requester_shift': {'id': 5, 'name': 'Normal 2'},
        'target_shift': {'id': 4, 'name': 'Normal'},
        'approver': None,
        'rejecter': None,
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlySubmissionMirrors(TransactionCase):
    """Pemetaan payload pengajuan ke kolom cermin.

    Server mengirim pegawai, penyetuju, dan shift sebagai objek bersarang.
    Yang diuji di sini adalah bahwa objek itu benar-benar dibaca, bukan
    sekadar disimpan mentah di `raw_payload`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _mirror(self, model_name, row):
        model = self.env[model_name]
        values = model._mirror_values(self.company, row)
        self.assertTrue(values, '%s menolak baris: %r' % (model_name, row))
        return model.create(values)

    def test_cuti_memakai_objek_bersarang(self):
        leave = self._mirror('presenly.saas.leave', leave_row())

        self.assertEqual(leave.reference_number, 'CT/2026/00001')
        self.assertEqual(leave.employee_nopeg, 'iksg-rangga')
        self.assertEqual(leave.employee_name, 'rangga')
        self.assertEqual(leave.leave_type_name, 'Cuti Tahunan')
        self.assertEqual(leave.location_name, 'Kantor Pusat')
        self.assertEqual(leave.approver_name, 'yusril')
        self.assertEqual(leave.total_days, 3.0)
        self.assertEqual(str(leave.leave_date), '2026-09-21')
        self.assertEqual(leave.status, 'approved')

    def test_lembur(self):
        overtime = self._mirror('presenly.saas.overtime', overtime_row())

        self.assertEqual(overtime.employee_name, 'rangga')
        self.assertEqual(overtime.total_hours, 2.5)
        self.assertEqual(overtime.overtime_pay, 150000.0)
        self.assertTrue(overtime.within_radius)
        self.assertEqual(overtime.approver_name, 'yusril')
        self.assertEqual(overtime.location_name, 'Kantor Pusat')

    def test_surat_dokter(self):
        certificate = self._mirror('presenly.saas.medical.certificate', medical_row())

        self.assertEqual(certificate.dc_number, 'DC/2026/00001')
        self.assertEqual(certificate.employee_name, 'yusril')
        self.assertEqual(certificate.reason, 'Demam')
        # Penyetuju boleh kosong; itu keadaan wajar, bukan galat.
        self.assertFalse(certificate.approver_name)

    def test_koreksi_presensi_memuat_shift_dan_tiga_penyetuju(self):
        correction = self._mirror(
            'presenly.saas.attendance.correction', correction_row()
        )

        self.assertEqual(correction.shift_name, 'Normal 2')
        self.assertEqual(correction.original_shift_name, 'Normal')
        self.assertEqual(correction.tl_approver_name, 'yusril')
        self.assertEqual(correction.manager_approver_name, 'boss')
        self.assertFalse(correction.rejecter_name)

    def test_tukar_shift(self):
        swap = self._mirror('presenly.saas.shift.swap', swap_row())

        self.assertEqual(swap.requester_name, 'rangga')
        self.assertEqual(swap.target_name, 'yusril')
        self.assertEqual(swap.requester_shift_name, 'Normal 2')
        self.assertEqual(swap.target_shift_name, 'Normal')
        self.assertEqual(swap.status, 'pending')

    def test_baris_tanpa_id_ditolak(self):
        for model_name, row in [
            ('presenly.saas.leave', leave_row(id=None)),
            ('presenly.saas.overtime', overtime_row(id=None)),
            ('presenly.saas.medical.certificate', medical_row(id=None)),
            ('presenly.saas.attendance.correction', correction_row(id=None)),
            ('presenly.saas.shift.swap', swap_row(id=None)),
        ]:
            self.assertFalse(self.env[model_name]._mirror_values(self.company, row))

    def test_relasi_kosong_tidak_menggagalkan_baris(self):
        leave = self._mirror('presenly.saas.leave', leave_row(
            employee=None, leave_type=None, location=None, approver=None,
        ))
        self.assertFalse(leave.employee_name)
        self.assertFalse(leave.leave_type_name)


@tagged('post_install', '-at_install')
class TestPresenlySubmissionRangePull(TransactionCase):
    """Penarikan per rentang: bulan lain tidak boleh ikut terhapus."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
            'api_key': 'k', 'retry_count': 0,
        })
        self.Leave = self.env['presenly.saas.leave']
        self.Leave.search([]).unlink()

    def test_rentang_hanya_mengganti_bulannya_sendiri(self):
        # Agustus sudah tercermin sebelumnya.
        self.Leave._mirror_replace(self.company, [
            leave_row(id=99, leave_date='2026-08-10', reference_number='CT/AGUSTUS'),
        ])
        self.assertEqual(self.Leave.search_count([]), 1)

        captured = []

        def fake_resource(resource, params=None):
            captured.append((resource, params))
            if resource != 'leaves':
                return EMPTY_PAGE
            return {'data': [leave_row(id=11)], 'meta': {'total': 1, 'total_pages': 1}}

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource), \
             patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=EMPTY_PAGE):
            summary, error = self.config._pull_period_datasets(9, 2026)

        self.assertFalse(error)
        self.assertEqual(summary['rows']['leaves'], 1)
        # Baris Agustus tetap ada; hanya September yang diganti.
        self.assertEqual(self.Leave.search_count([]), 2)
        self.assertTrue(self.Leave.search([('reference_number', '=', 'CT/AGUSTUS')]))

    def test_mengirim_batas_tanggal_ke_server(self):
        captured = []

        def fake_resource(resource, params=None):
            captured.append((resource, params))
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource):
            self.config._pull_period_datasets(9, 2026)

        # Lima pengajuan ditambah timesheet, masing-masing dibatasi ke bulan
        # yang diminta.
        self.assertEqual(len(captured), 6)
        for resource, params in captured:
            self.assertEqual(params['since'], '2026-09-01', resource)
            self.assertEqual(params['until'], '2026-09-30', resource)

    def test_baris_tanpa_tanggal_ikut_diganti(self):
        """Baris tanpa tanggal tidak boleh tertinggal sebagai salinan basi.

        Baris yang tidak punya tanggal tidak masuk rentang mana pun, jadi tanpa
        aturan ini ia tidak pernah ikut diganti — dan pengajuan yang sudah
        dihapus di aplikasi tetap terlihat di sini. Server yang sudah diperbaiki
        mengirimkannya di setiap rentang.
        """
        self.Leave._mirror_replace(self.company, [
            leave_row(id=98, reference_number='CT/LAMA', leave_date=None,
                      start_date=None, end_date=None),
        ])

        self.Leave._mirror_replace_range(
            self.company,
            [leave_row(id=11),
             leave_row(id=97, reference_number='CT/BARU', leave_date=None,
                       start_date=None, end_date=None)],
            date(2026, 9, 1), date(2026, 9, 30),
        )

        self.assertEqual(
            sorted(self.Leave.search([]).mapped('reference_number')),
            ['CT/2026/00001', 'CT/BARU'],
        )

    def test_baris_tanpa_tanggal_tidak_hilang_bila_server_belum_mengirimnya(self):
        """Sisi aman: server yang belum menyertakannya tidak membuat baris hilang.

        Kalau baris tanpa tanggal dihapus tanpa penggantinya, salinan yang masih
        ada di aplikasi justru ikut terbuang. Karena itu penghapusannya hanya
        dilakukan kalau tarikannya sendiri memuat baris seperti itu.
        """
        self.Leave._mirror_replace(self.company, [
            leave_row(id=98, reference_number='CT/LAMA', leave_date=None,
                      start_date=None, end_date=None),
        ])

        self.Leave._mirror_replace_range(
            self.company, [leave_row(id=11)], date(2026, 9, 1), date(2026, 9, 30),
        )

        self.assertTrue(self.Leave.search([('reference_number', '=', 'CT/LAMA')]))

    def test_galat_dikembalikan_sebagai_nilai_dan_tidak_diklaim_berhasil(self):
        failure = SaasClientError('down', code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_resource', side_effect=failure):
            summary, error = self.config._pull_period_datasets(9, 2026)

        self.assertTrue(error)
        self.assertEqual(summary['rows'], {})
        log = self.env['presenly.saas.sync.log'].search([], order='id desc', limit=1)
        self.assertFalse(log.success)

    def test_satu_jenis_gagal_menghentikan_bulan_itu(self):
        # Jenis pertama berhasil, jenis kedua gagal: yang pertama tetap tersimpan.
        def fake_resource(resource, params=None):
            if resource == 'leaves':
                return {'data': [leave_row(id=11)], 'meta': {'total': 1, 'total_pages': 1}}
            raise SaasClientError('down', code='NETWORK_ERROR')

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource):
            summary, error = self.config._pull_period_datasets(9, 2026)

        self.assertTrue(error)
        self.assertEqual(summary['rows'], {'leaves': 1})
        self.assertEqual(self.Leave.search_count([]), 1)

    def test_baris_terpotong_dilaporkan(self):
        def fake_resource(resource, params=None):
            if resource != 'leaves':
                return EMPTY_PAGE
            # Server mengaku 5000 baris, batas halaman membuat kita berhenti awal.
            # Tiap halaman berisi baris berbeda, seperti server sungguhan.
            page = int((params or {}).get('page') or 1)
            return {
                'data': [leave_row(id=100 + page)],
                'meta': {'total': 5000, 'total_pages': 5000},
            }

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource):
            summary, _error = self.config._pull_period_datasets(9, 2026)

        self.assertEqual(len(summary['truncated']), 1)
        self.assertIn('leaves', summary['truncated'][0])

    def test_penarikan_mengganti_tidak_menumpuk(self):
        def fake_resource(resource, params=None):
            if resource != 'leaves':
                return EMPTY_PAGE
            return {'data': [leave_row(id=11)], 'meta': {'total': 1, 'total_pages': 1}}

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource):
            self.config._pull_period_datasets(9, 2026)
            self.config._pull_period_datasets(9, 2026)

        # Ditarik dua kali, hasilnya tetap satu baris.
        self.assertEqual(self.Leave.search_count([]), 1)


@tagged('post_install', '-at_install')
class TestPresenlyPeriodRangeCombined(TransactionCase):
    """Satu penarikan periode mencakup presensi dan pengajuan sekaligus."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
            'api_key': 'k', 'retry_count': 0,
        })
        self.env['presenly.saas.leave'].search([]).unlink()

    def test_ringkasan_memuat_pengajuan(self):
        def fake_resource(resource, params=None):
            if resource == 'leaves':
                return {'data': [leave_row(id=11)], 'meta': {'total': 1, 'total_pages': 1}}
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource), \
             patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=EMPTY_PAGE):
            summary, error = self.config._pull_period_range(9, 2026, months_back=2)

        self.assertFalse(error)
        self.assertEqual(summary['months'], 2)
        # Satu bulan menarik satu baris cuti, dua bulan berarti dua.
        self.assertEqual(summary['datasets']['leaves'], 2)
        self.assertEqual(sum(summary['datasets'].values()), 2)

    def test_gagal_di_tengah_rentang_tidak_mengklaim_bulan_selesai(self):
        calls = {'n': 0}

        def fake_resource(resource, params=None):
            calls['n'] += 1
            # Gagal pada penarikan bulan kedua (enam dataset per bulan).
            if calls['n'] > 6:
                raise SaasClientError('down', code='NETWORK_ERROR')
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource), \
             patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=EMPTY_PAGE):
            summary, error = self.config._pull_period_range(9, 2026, months_back=2)

        self.assertTrue(error)
        self.assertEqual(summary['months'], 1)

    def test_koneksi_nonaktif_ditolak(self):
        self.config.write({'enabled': False})
        with self.assertRaises(UserError):
            self.config._pull_period_range(9, 2026, months_back=1)
