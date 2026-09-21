from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.saas_client import PresenlySaasClient, SaasClientError


def log_row(**overrides):
    row = {
        'id': 3,
        'session_key': '2:2026-09-21:default',
        'user_id': 2,
        'work_date': '2026-09-21',
        'location_id': 1,
        'status': 'closed',
        'late_minutes': 571,
        'is_overtime': False,
        'schedule_id': 0,
        'schedule_segment_id': 0,
        'schedule_source': 'daily',
        'check_in_time': '2026-09-21T01:48:28.000Z',
        'check_out_time': '2026-09-21T02:41:52.000Z',
        'check_in_latitude': -7.1642,
        'check_in_longitude': 112.6512,
        'created_at': '2026-09-21T01:48:28.000Z',
        'updated_at': '2026-09-21T02:41:52.000Z',
        'employee': {'id': 2, 'name': 'rangga', 'nopeg': 'iksg-rangga', 'project': 'Proyek A'},
        'location': {'id': 1, 'name': 'Central Parkir', 'tenantClient': {'id': 1, 'name': 'Testing Client'}},
        'shift': {'id': 1, 'shift_name': 'Pagi'},
        'checkInMode': {'id': 1, 'name': 'Work From Office'},
        'checkOutMode': {'id': 1, 'name': 'Work From Office'},
    }
    row.update(overrides)
    return row


def recap_row(**overrides):
    row = {
        'user_id': 2,
        'user': {'id': 2, 'name': 'rangga', 'nopeg': 'iksg-rangga', 'project': 'Proyek A'},
        'month': 9,
        'year': 2026,
        'attendance_count': 1,
        'total_late_minutes': 571,
        'absent_count': 0,
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlyExternalFeature(TransactionCase):
    """Katalog fitur eksternal: cermin, bukan arsip."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Feature = cls.env['presenly.saas.external.feature']

    def setUp(self):
        super().setUp()
        self.Feature.search([]).unlink()

    def test_sync_creates_and_maps_status(self):
        self.Feature._sync_from_payload(self.config, [
            {'feature': 'attendance-logs', 'path': '/v1/presenly/attendance-logs',
             'status': 'available', 'web_page': 'x', 'description': 'Log presensi'},
            {'feature': 'leaves', 'path': '/v1/presenly/leaves',
             'status': 'planned', 'description': 'Cuti'},
        ])

        available = self.Feature.search([('status', '=', 'available')])
        self.assertEqual(available.code, 'attendance-logs')
        self.assertEqual(len(self.Feature.search([])), 2)

    def test_status_yang_tidak_dikenal_dianggap_planned(self):
        # Hanya 'available' yang membuka pintu; nilai aneh tidak boleh
        # membuat fitur tampak siap dipakai.
        self.Feature._sync_from_payload(self.config, [
            {'feature': 'aneh', 'path': '/x', 'status': 'whatever'},
        ])
        self.assertEqual(self.Feature.search([]).status, 'planned')

    def test_sync_replaces_so_removed_features_disappear(self):
        self.Feature._sync_from_payload(self.config, [
            {'feature': 'a', 'path': '/a', 'status': 'available'},
            {'feature': 'b', 'path': '/b', 'status': 'available'},
        ])
        self.Feature._sync_from_payload(self.config, [
            {'feature': 'a', 'path': '/a', 'status': 'available'},
        ])
        self.assertEqual(self.Feature.search([]).mapped('code'), ['a'])

    def test_sync_ignores_malformed_and_duplicate_entries(self):
        self.Feature._sync_from_payload(self.config, [
            {'feature': 'a', 'path': '/a', 'status': 'available'},
            {'feature': 'a', 'path': '/a-lagi', 'status': 'available'},
            {'path': '/tanpa-kode', 'status': 'available'},
            'bukan dict',
            None,
        ])
        self.assertEqual(len(self.Feature.search([])), 1)
        self.assertEqual(self.Feature.search([]).path, '/a')

    # ------------------------------------------------------------------
    # Penarikan
    # ------------------------------------------------------------------
    def test_pull_features_menulis_cermin_dan_log(self):
        self.config.write({'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
                           'api_key': 'k', 'retry_count': 0})
        envelope = {'data': [
            {'feature': 'attendance-logs', 'path': '/v1/presenly/attendance-logs',
             'status': 'available', 'description': 'Log presensi'},
        ], 'meta': {'count': 1, 'schema_version': '1.0.0'}}

        with patch.object(PresenlySaasClient, 'get_presenly_features', return_value=envelope):
            result = self.config.action_pull_external_features()

        self.assertEqual(result['params']['type'], 'success')
        self.assertEqual(len(self.Feature.search([])), 1)
        log = self.env['presenly.saas.sync.log'].search(
            [('company_id', '=', self.company.id)], order='id desc', limit=1)
        self.assertTrue(log.success)
        self.assertEqual(log.endpoint, '/api/external/v1/presenly/features')

    def test_pull_menolak_koneksi_yang_nonaktif(self):
        self.config.write({'enabled': False})
        with self.assertRaises(UserError):
            self.config.action_pull_external_features()

    def test_pull_mencatat_kegagalan(self):
        self.config.write({'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
                           'api_key': 'k', 'retry_count': 0})
        error = SaasClientError('Tidak dapat menghubungi server Presenly SaaS.',
                                code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_presenly_features', side_effect=error):
            result = self.config.action_pull_external_features()

        # Dilaporkan sebagai notifikasi, bukan exception, supaya catatan audit
        # tidak ikut ter-rollback bersama exception yang naik ke layer RPC.
        self.assertEqual(result['params']['type'], 'danger')
        log = self.env['presenly.saas.sync.log'].search(
            [('company_id', '=', self.company.id)], order='id desc', limit=1)
        self.assertFalse(log.success)
        self.assertEqual(log.endpoint, '/api/external/v1/presenly/features')


@tagged('post_install', '-at_install')
class TestPresenlyAttendanceMirror(TransactionCase):
    """Cermin log dan rekap presensi."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Log = cls.env['presenly.saas.attendance.log']
        cls.Recap = cls.env['presenly.saas.attendance.recap']

    def setUp(self):
        super().setUp()
        self.config.write({'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
                           'api_key': 'k', 'retry_count': 0})
        self.Log.search([]).unlink()
        self.Recap.search([]).unlink()

    # ------------------------------------------------------------------
    # Pemetaan payload
    # ------------------------------------------------------------------
    def test_log_mapping_takes_names_from_nested_objects(self):
        values = self.Log._values_from_payload(self.company, log_row())

        self.assertEqual(values['external_id'], 3)
        self.assertEqual(values['employee_name'], 'rangga')
        self.assertEqual(values['employee_nopeg'], 'iksg-rangga')
        self.assertEqual(values['location_name'], 'Central Parkir')
        self.assertEqual(values['tenant_client_name'], 'Testing Client')
        self.assertEqual(values['shift_name'], 'Pagi')
        self.assertEqual(values['check_in_mode_name'], 'Work From Office')
        self.assertEqual(values['late_minutes'], 571)
        self.assertEqual(values['status'], 'closed')
        self.assertTrue(values['raw_payload'])

    def test_log_mapping_menolak_baris_tanpa_id(self):
        self.assertIsNone(self.Log._values_from_payload(self.company, {'work_date': '2026-09-21'}))
        self.assertIsNone(self.Log._values_from_payload(self.company, 'bukan dict'))

    def test_log_mapping_aman_untuk_relasi_yang_hilang(self):
        row = log_row()
        row.pop('employee')
        row.pop('location')
        row.pop('shift')
        values = self.Log._values_from_payload(self.company, row)

        self.assertFalse(values['employee_name'])
        self.assertFalse(values['location_name'])
        self.assertFalse(values['tenant_client_name'])

    def test_status_yang_tidak_dikenal_tidak_dipaksakan(self):
        values = self.Log._values_from_payload(self.company, log_row(status='tepat waktu'))
        self.assertFalse(values['status'])

    def test_recap_mapping(self):
        values = self.Recap._values_from_payload(self.company, recap_row())

        self.assertEqual(values['user_id'], 2)
        self.assertEqual(values['employee_name'], 'rangga')
        self.assertEqual(values['month'], 9)
        self.assertEqual(values['attendance_count'], 1)
        self.assertEqual(values['total_late_minutes'], 571)

    # ------------------------------------------------------------------
    # Cermin diganti, bukan ditumpuk
    # ------------------------------------------------------------------
    def test_upsert_memperbarui_baris_yang_sama(self):
        self.Log._upsert_rows(self.company, [log_row(late_minutes=10)])
        self.Log._upsert_rows(self.company, [log_row(late_minutes=99)])

        self.assertEqual(len(self.Log.search([])), 1)
        self.assertEqual(self.Log.search([]).late_minutes, 99)

    def test_replace_scope_hanya_menghapus_rentang_yang_diminta(self):
        from datetime import date
        self.Log._upsert_rows(self.company, [
            log_row(id=1, work_date='2026-08-15'),
            log_row(id=2, work_date='2026-09-15'),
        ])

        self.Log._replace_scope(self.company, date(2026, 9, 1), date(2026, 9, 30))

        remaining = self.Log.search([])
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining.external_id, 1)

    def test_replace_scope_recap_per_bulan(self):
        self.Recap._upsert_rows(self.company, [recap_row(month=8), recap_row(month=9)])
        self.Recap._replace_scope(self.company, 9, 2026)
        self.assertEqual(self.Recap.search([]).mapped('month'), [8])

    # ------------------------------------------------------------------
    # Penarikan berhalaman
    # ------------------------------------------------------------------
    def test_fetch_pages_mengikuti_total_pages(self):
        envelopes = [
            {'data': [{'id': 1}], 'meta': {'total': 3, 'total_pages': 3}},
            {'data': [{'id': 2}], 'meta': {'total': 3, 'total_pages': 3}},
            {'data': [{'id': 3}], 'meta': {'total': 3, 'total_pages': 3}},
        ]
        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=envelopes) as call:
            rows, meta, pages = self.config._fetch_pages(
                PresenlySaasClient.get_attendance_logs, {'limit': 1})

        self.assertEqual([r['id'] for r in rows], [1, 2, 3])
        self.assertEqual(pages, 3)
        self.assertEqual([c[0][0]['page'] for c in [args for args in call.call_args_list]], [1, 2, 3])

    def test_fetch_pages_berhenti_di_batas_halaman(self):
        envelope = {'data': [{'id': 1}], 'meta': {'total': 9999, 'total_pages': 9999}}
        with patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=envelope):
            rows, meta, _pages = self.config._fetch_pages(
                PresenlySaasClient.get_attendance_logs, {}, max_pages=3)

        # Batasnya dihormati, dan `meta.total` tetap dilaporkan supaya
        # pemanggil tahu hasilnya terpotong.
        self.assertEqual(len(rows), 3)
        self.assertEqual(meta['total'], 9999)

    def test_pull_attendance_menulis_dua_dataset_dan_melaporkan_terpotong(self):
        logs_envelope = {'data': [log_row()], 'meta': {'total': 50, 'total_pages': 50}}
        recap_envelope = {'data': [recap_row()], 'meta': {'total': 1, 'schema_version': '1.0.0'}}

        with patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=logs_envelope), \
             patch.object(PresenlySaasClient, 'get_attendance_recap', return_value=recap_envelope):
            summary, error = self.config._pull_attendance(9, 2026)

        self.assertFalse(error)
        self.assertEqual(summary['logs'], 1)
        self.assertEqual(summary['recap'], 1)
        self.assertEqual(summary['period'], '09/2026')
        self.assertTrue(summary['truncated'], 'hasil terpotong harus dilaporkan')

        self.assertEqual(len(self.Log.search([])), 1)
        self.assertEqual(len(self.Recap.search([])), 1)

        endpoints = self.env['presenly.saas.sync.log'].search(
            [('company_id', '=', self.company.id)]).mapped('endpoint')
        self.assertIn('/api/external/v1/presenly/attendance-logs', endpoints)
        self.assertIn('/api/external/v1/presenly/attendance-recap', endpoints)

    def test_pull_attendance_gagal_dikembalikan_sebagai_nilai(self):
        failure = SaasClientError('down', code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=failure):
            summary, error = self.config._pull_attendance(9, 2026)

        self.assertTrue(error)
        self.assertEqual(summary['logs'], 0)
        log = self.env['presenly.saas.sync.log'].search(
            [('company_id', '=', self.company.id)], order='id desc', limit=1)
        self.assertFalse(log.success)
        self.assertEqual(log.endpoint, '/api/external/v1/presenly/attendance-logs')

    def test_upsert_menghitung_baris_unik_saja(self):
        # Halaman yang tumpang tindih tidak boleh membuat hitungan membengkak
        # atau menulis baris yang sama berulang kali.
        written = self.Log._upsert_rows(self.company, [log_row(), log_row(), log_row(id=4)])
        self.assertEqual(written, 2)
        self.assertEqual(len(self.Log.search([])), 2)


@tagged('post_install', '-at_install')
class TestPresenlyPullWizard(TransactionCase):
    """Wizard periode."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)
        cls.Wizard = cls.env['presenly.saas.pull.wizard']

    def test_default_periode_adalah_bulan_berjalan(self):
        from odoo import fields
        today = fields.Date.context_today(self.Wizard)
        wizard = self.Wizard.create({})

        self.assertEqual(int(wizard.month), today.month)
        self.assertEqual(wizard.year, today.year)

    def test_action_pull_mengembalikan_notifikasi_dan_menutup_dialog(self):
        self.config.write({'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
                           'api_key': 'k', 'retry_count': 0})
        wizard = self.Wizard.create({'month': '9', 'year': 2026})
        empty = {'data': [], 'meta': {'total': 0, 'schema_version': '1.0.0'}}

        with patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=empty), \
             patch.object(PresenlySaasClient, 'get_attendance_recap', return_value=empty):
            result = wizard.action_pull()

        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn('09/2026', result['params']['title'])
