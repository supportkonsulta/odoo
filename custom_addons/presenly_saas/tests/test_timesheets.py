from datetime import date
from unittest.mock import patch

from odoo import _
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.presenly_saas_timesheet_mirrors import hours_between
from ..services.saas_client import PresenlySaasClient

EMPTY_PAGE = {'data': [], 'meta': {'total': 0, 'total_pages': 0}}


def project_row(**overrides):
    row = {
        'id': 7,
        'project_code': 'PRJ-001',
        'project_name': 'Pendampingan IKM',
        'sub_code': 'A',
        'description': 'Pendampingan sertifikasi',
        'grup': 'Grup 1',
        'pk': 'PK-2026',
        'has_timesheet': True,
        'internal_company': {'id': 2, 'name': 'PT KONSULTA SEMEN GRESIK'},
        'created_at': '2026-01-05T02:00:00.000Z',
    }
    row.update(overrides)
    return row


def timesheet_row(**overrides):
    row = {
        'id': 31,
        'date': '2026-09-21',
        'category': 'Pendampingan',
        'description': 'Kunjungan lapangan',
        'start_time': '08:00:00',
        'end_time': '12:30:00',
        'status': 'approved',
        'rating': 4.5,
        'comment': 'Rapi',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'project': {'id': 7, 'code': 'PRJ-001', 'name': 'Pendampingan IKM'},
        'approver': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
        'shift': {'id': 2, 'name': 'Normal 2'},
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlyHours(TransactionCase):
    """Perhitungan jam: angka turunan, jadi batasnya harus jelas."""

    def test_menghitung_selisih_jam(self):
        self.assertEqual(hours_between('08:00:00', '12:30:00'), 4.5)
        self.assertEqual(hours_between('07:30:00', '16:30:00'), 9.0)

    def test_kosong_menghasilkan_nol(self):
        self.assertEqual(hours_between(False, '12:00:00'), 0.0)
        self.assertEqual(hours_between('08:00:00', None), 0.0)
        self.assertEqual(hours_between('', ''), 0.0)

    def test_shift_lewat_tengah_malam_tidak_ditebak(self):
        # 22:00 -> 02:00 bisa berarti 4 jam atau -20 jam. Menebak lebih buruk
        # daripada mengosongkan, jadi hasilnya 0 dan bukan angka negatif.
        self.assertEqual(hours_between('22:00:00', '02:00:00'), 0.0)

    def test_jam_tidak_terbaca_menghasilkan_nol(self):
        self.assertEqual(hours_between('pagi', '12:00:00'), 0.0)
        self.assertEqual(hours_between('25:00:00', '12:00:00'), 0.0)
        self.assertEqual(hours_between('12:00:00', '12:70:00'), 0.0)

    def test_jam_sama_menghasilkan_nol(self):
        self.assertEqual(hours_between('08:00:00', '08:00:00'), 0.0)


@tagged('post_install', '-at_install')
class TestPresenlyTimesheetMirror(TransactionCase):
    """Pemetaan payload timesheet dan proyek ke kolom cermin."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _mirror(self, model_name, row):
        model = self.env[model_name]
        values = model._mirror_values(self.company, row)
        self.assertTrue(values, '%s menolak baris: %r' % (model_name, row))
        return model.create(values)

    def test_timesheet_memakai_objek_bersarang(self):
        sheet = self._mirror('presenly.saas.timesheet', timesheet_row())

        self.assertEqual(sheet.employee_nopeg, 'iksg-rangga')
        self.assertEqual(sheet.employee_name, 'rangga')
        self.assertEqual(sheet.approver_name, 'yusril')
        self.assertEqual(sheet.shift_name, 'Normal 2')
        self.assertEqual(sheet.rating, 4.5)
        self.assertEqual(sheet.status, 'approved')
        self.assertEqual(str(sheet.date), '2026-09-21')

    def test_proyek_diambil_dari_kode_dan_nama(self):
        # Proyek dikirim sebagai {id, code, name}, bukan {id, name} seperti
        # relasi lain. Kodenya harus ikut terbaca, bukan tertukar dengan nama.
        sheet = self._mirror('presenly.saas.timesheet', timesheet_row())

        self.assertEqual(sheet.project_code, 'PRJ-001')
        self.assertEqual(sheet.project_name, 'Pendampingan IKM')

    def test_jam_dihitung_saat_dipetakan(self):
        sheet = self._mirror('presenly.saas.timesheet', timesheet_row())
        self.assertEqual(sheet.hours, 4.5)

    def test_proyek_memakai_objek_perusahaan_internal(self):
        project = self._mirror('presenly.saas.project', project_row())

        self.assertEqual(project.project_code, 'PRJ-001')
        self.assertEqual(project.internal_company_id, 2)
        self.assertEqual(project.internal_company_name, 'PT KONSULTA SEMEN GRESIK')
        self.assertTrue(project.has_timesheet)
        # Kolom dari sistem SIK tetap apa adanya.
        self.assertEqual(project.grup, 'Grup 1')
        self.assertEqual(project.pk, 'PK-2026')

    def test_relasi_kosong_tidak_menggagalkan_baris(self):
        sheet = self._mirror('presenly.saas.timesheet', timesheet_row(
            employee=None, project=None, approver=None, shift=None,
            start_time=None, end_time=None, rating=None,
        ))
        self.assertFalse(sheet.employee_name)
        self.assertFalse(sheet.project_code)
        self.assertEqual(sheet.hours, 0.0)
        self.assertEqual(sheet.rating, 0.0)

    def test_baris_tanpa_id_ditolak(self):
        self.assertFalse(
            self.env['presenly.saas.timesheet']._mirror_values(
                self.company, timesheet_row(id=None))
        )
        self.assertFalse(
            self.env['presenly.saas.project']._mirror_values(
                self.company, project_row(id=None))
        )


@tagged('post_install', '-at_install')
class TestPresenlyTimesheetPull(TransactionCase):
    """Penarikan: timesheet ikut penarikan periode, proyek ikut referensi."""

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
        self.company = self.env.company
        self.Sheet = self.env['presenly.saas.timesheet']
        self.Project = self.env['presenly.saas.project']
        self.Sheet.search([]).unlink()
        self.Project.search([]).unlink()

    def test_timesheet_ikut_penarikan_periode(self):
        terlihat = []

        def fake_resource(resource, params=None):
            terlihat.append(resource)
            if resource == 'timesheets':
                return {'data': [timesheet_row()], 'meta': {'total': 1, 'total_pages': 1}}
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource):
            summary, error = self.config._pull_period_datasets(9, 2026)

        self.assertFalse(error)
        self.assertIn('timesheets', terlihat)
        self.assertEqual(summary['rows']['timesheets'], 1)
        # Lima pengajuan ditambah timesheet.
        self.assertEqual(len(terlihat), 6)
        self.assertEqual(self.Sheet.search_count([]), 1)

    def test_ringkasan_periode_memuat_timesheet(self):
        def fake_resource(resource, params=None):
            if resource == 'timesheets':
                return {'data': [timesheet_row()], 'meta': {'total': 1, 'total_pages': 1}}
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource), \
             patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=EMPTY_PAGE), \
             patch.object(PresenlySaasClient, 'get_attendance_recap', return_value=EMPTY_PAGE):
            summary, error = self.config._pull_period_range(9, 2026, months_back=2)

        self.assertFalse(error)
        self.assertEqual(summary['datasets']['timesheets'], 2)
        self.assertEqual(
            sum(v for k, v in summary['datasets'].items() if k != 'timesheets'), 0
        )

    def test_proyek_ikut_penarikan_referensi(self):
        terlihat = []

        def fake_resource(resource, params=None):
            terlihat.append(resource)
            if resource == 'projects':
                return {'data': [project_row()], 'meta': {'total': 1, 'total_pages': 1}}
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource):
            summary, error = self.config._pull_reference_data()

        self.assertFalse(error)
        self.assertIn('projects', terlihat)
        self.assertEqual(summary['projects'], 1)
        self.assertEqual(self.Project.search_count([]), 1)

    def test_timesheet_ikut_jendela_bergulir(self):
        from dateutil.relativedelta import relativedelta
        self.config.write({'retention_months': 12})
        tua = date.today() - relativedelta(months=18)
        self.Sheet._mirror_replace(self.company, [
            timesheet_row(id=1, date=str(tua)),
            timesheet_row(id=2, date=str(date.today())),
        ])

        removed = self.config._prune_mirrors()

        self.assertEqual(removed['presenly.saas.timesheet'], 1)
        self.assertEqual(self.Sheet.search([]).external_id, 2)

    def test_proyek_tidak_pernah_dihapus_jendela_bergulir(self):
        self.Project._mirror_replace(self.company, [project_row()])
        self.config.write({'retention_months': 1})

        removed = self.config._prune_mirrors()

        self.assertNotIn('presenly.saas.project', removed)
        self.assertEqual(self.Project.search_count([]), 1)
