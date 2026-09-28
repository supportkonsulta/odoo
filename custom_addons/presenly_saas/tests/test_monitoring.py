from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.saas_client import PresenlySaasClient, SaasClientError


# Halaman kosong untuk resource pengajuan, supaya penarikan periode tidak
# menyentuh jaringan sungguhan.
EMPTY_PAGE = {'data': [], 'meta': {'total': 0, 'total_pages': 0}}


def log_row(**overrides):
    row = {
        'id': 3,
        'session_key': '2:2026-09-21:default',
        'user_id': 2,
        'work_date': '2026-09-21',
        'location_id': 1,
        'status': 'closed',
        'late_minutes': 0,
        'employee': {'id': 2, 'name': 'rangga', 'nopeg': 'iksg-rangga'},
        'location': {'id': 1, 'name': 'Central Parkir'},
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlyPeriodRange(TransactionCase):
    """Penarikan rentang: beberapa bulan digabung, dan kegagalan tidak diklaim."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Log = cls.env['presenly.saas.attendance.log']

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
            'api_key': 'k', 'retry_count': 0,
        })
        self.Log.search([]).unlink()

    def test_rentang_menarik_beberapa_bulan_dan_menggabungkan_hasil(self):
        def fake_logs(params, _self=None):
            return {
                'data': [log_row(id=int(params['page']), work_date='2026-09-15')],
                'meta': {'total': 1, 'total_pages': 1},
            }

        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=fake_logs), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=EMPTY_PAGE):
            summary, error = self.config._pull_period_range(9, 2026, months_back=3)

        self.assertFalse(error)
        self.assertEqual(summary['months'], 3)
        self.assertEqual(summary['periods'], ['07/2026', '08/2026', '09/2026'])
        self.assertEqual(summary['logs'], 3)

    def test_rentang_berhenti_dan_mengembalikan_galat(self):
        failure = SaasClientError('down', code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=failure), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=EMPTY_PAGE):
            summary, error = self.config._pull_period_range(9, 2026, months_back=3)

        self.assertTrue(error)
        # Tidak ada bulan yang diklaim selesai.
        self.assertEqual(summary['months'], 0)
        log = self.env['presenly.saas.sync.log'].search([], order='id desc', limit=1)
        self.assertFalse(log.success)

    def test_rentang_melaporkan_hasil_terpotong(self):
        def fake_logs(params, _self=None):
            # Server punya 9999 baris, batas halaman membuat kita berhenti lebih awal.
            return {'data': [log_row(id=1)], 'meta': {'total': 9999, 'total_pages': 9999}}

        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=fake_logs), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=EMPTY_PAGE):
            summary, _error = self.config._pull_period_range(9, 2026, months_back=1)

        self.assertTrue(summary['truncated'])

    def test_rentang_menolak_koneksi_nonaktif(self):
        self.config.write({'enabled': False})
        with self.assertRaises(UserError):
            self.config._pull_period_range(9, 2026, months_back=1)

    def test_log_presensi_diganti_per_rentang(self):
        """Bulan yang ditarik diganti; bulan lain tidak ikut terhapus."""
        self.Log._upsert_rows(self.company, [
            log_row(id=901, work_date='2026-08-10'),
            log_row(id=902, work_date='2026-09-10'),
        ])

        with patch.object(PresenlySaasClient, 'get_attendance_logs',
                          return_value={'data': [log_row(id=903, work_date='2026-09-11')],
                                        'meta': {'total': 1, 'total_pages': 1}}), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=EMPTY_PAGE):
            _summary, error = self.config._pull_period_range(9, 2026, months_back=1)

        self.assertFalse(error)
        self.assertEqual(
            sorted(self.Log.search([]).mapped('external_id')), [901, 903],
            'September diganti, Agustus dibiarkan',
        )


@tagged('post_install', '-at_install')
class TestPresenlyPullWizardRange(TransactionCase):
    """Wizard: jumlah bulan divalidasi sebelum penarikan."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)
        cls.Wizard = cls.env['presenly.saas.pull.wizard']

    def test_default_satu_bulan(self):
        self.assertEqual(self.Wizard.create({}).months_back, 1)

    def test_menolak_jumlah_bulan_kurang_dari_satu(self):
        self.config.write({'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
                           'api_key': 'k', 'retry_count': 0})
        wizard = self.Wizard.create({'month': '9', 'year': 2026, 'months_back': 0})
        with self.assertRaises(UserError):
            wizard.action_pull()

    def test_notifikasi_menyebut_jumlah_bulan_dan_rentang(self):
        self.config.write({'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
                           'api_key': 'k', 'retry_count': 0})
        empty = {'data': [], 'meta': {'total': 0, 'total_pages': 0}}
        wizard = self.Wizard.create({'month': '9', 'year': 2026, 'months_back': 2})

        with patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=empty), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=empty):
            result = wizard.action_pull()

        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn('08/2026', result['params']['title'])
        self.assertIn('09/2026', result['params']['title'])
