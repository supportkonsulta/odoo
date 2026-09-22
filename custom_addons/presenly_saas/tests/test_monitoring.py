from unittest.mock import patch

from odoo.exceptions import UserError
from odoo import _
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


def recap_row(**overrides):
    row = {
        'user_id': 2,
        'user': {'id': 2, 'name': 'rangga', 'nopeg': 'iksg-rangga'},
        'month': 9,
        'year': 2026,
        'attendance_count': 1,
        'total_late_minutes': 0,
        'absent_count': 0,
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlyMonitoring(TransactionCase):
    """Uji silang monitoring dan penarikan rentang.

    Uji silang inilah yang membuat monitoring layak dipercaya: angkanya dihitung
    lokal dari cermin log, lalu dibandingkan dengan rekap yang dihitung server.
    Kalau keduanya berbeda, itu tanda cermin tidak lengkap dan harus terlihat.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Log = cls.env['presenly.saas.attendance.log']
        cls.Recap = cls.env['presenly.saas.attendance.recap']

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
            'api_key': 'k', 'retry_count': 0,
        })
        self.Log.search([]).unlink()
        self.Recap.search([]).unlink()

    def _pesan_uji_silang(self, key, lcount, llate, scount, slate):
        """Pesan uji silang yang diharapkan.

        Dibangun dari string sumber yang sama, bukan dari teks hasil terjemahan.
        Dengan begitu tes tidak bergantung pada bahasa pengguna, dan tetap gagal
        kalau pesannya suatu saat ditulis langsung tanpa `_()` sehingga tidak
        bisa diterjemahkan.
        """
    # Memakai `_()` polos, bukan `self.env._()`, karena modul ini memakai yang
    # polos. Di lingkungan tes `env.lang` bernilai kosong, sehingga
    # `self.env._()` mengembalikan teks sumber apa adanya, sementara `_()`
    # mengikuti bahasa pengguna seperti di produksi. Memakai mekanisme yang
    # sama membuat tes lulus di bahasa mana pun, dan tetap gagal kalau pesannya
    # ditulis langsung sehingga tidak bisa diterjemahkan.
        return _(
            '%(key)s: the mirrored log has %(lcount)s sessions/'
            '%(llate)s minutes, the server recap has %(scount)s sessions/'
            '%(slate)s minutes',
            key=key, lcount=lcount, llate=llate, scount=scount, slate=slate,
        )

    # ------------------------------------------------------------------
    # Uji silang
    # ------------------------------------------------------------------
    def test_cocok_saat_agregat_sama_dengan_rekap_server(self):
        self.Log._upsert_rows(self.company, [
            log_row(id=1, late_minutes=10),
            log_row(id=2, late_minutes=5),
        ])
        self.Recap._upsert_rows(self.company, [
            recap_row(attendance_count=2, total_late_minutes=15),
        ])

        self.assertEqual(self.config._crosscheck_attendance(9, 2026), [])

    def test_melaporkan_selisih_jumlah_sesi(self):
        self.Log._upsert_rows(self.company, [log_row(id=1)])
        self.Recap._upsert_rows(self.company, [recap_row(attendance_count=5)])

        mismatches = self.config._crosscheck_attendance(9, 2026)

        self.assertEqual(
            mismatches, [self._pesan_uji_silang('iksg-rangga', 1, 0, 5, 0)]
        )

    def test_melaporkan_selisih_menit_terlambat(self):
        self.Log._upsert_rows(self.company, [log_row(id=1, late_minutes=7)])
        self.Recap._upsert_rows(self.company, [
            recap_row(attendance_count=1, total_late_minutes=99),
        ])

        mismatches = self.config._crosscheck_attendance(9, 2026)

        self.assertEqual(
            mismatches, [self._pesan_uji_silang('iksg-rangga', 1, 7, 1, 99)]
        )

    def test_melaporkan_pegawai_yang_hanya_ada_di_satu_sisi(self):
        self.Log._upsert_rows(self.company, [log_row(id=1)])
        self.Recap._upsert_rows(self.company, [
            recap_row(user_id=9, user={'id': 9, 'name': 'lain', 'nopeg': 'iksg-lain'},
                      attendance_count=3, total_late_minutes=0),
        ])

        mismatches = self.config._crosscheck_attendance(9, 2026)

        # Dua baris: satu pegawai hanya di cermin log, satu hanya di rekap.
        self.assertEqual(len(mismatches), 2)

    def test_tidak_memakai_data_bulan_lain(self):
        self.Log._upsert_rows(self.company, [log_row(id=1, work_date='2026-08-15')])
        self.Recap._upsert_rows(self.company, [
            recap_row(month=9, attendance_count=1, total_late_minutes=0),
        ])

        # Log bulan Agustus tidak boleh dihitung untuk September.
        mismatches = self.config._crosscheck_attendance(9, 2026)

        self.assertEqual(
            mismatches, [self._pesan_uji_silang('iksg-rangga', 0, 0, 1, 0)]
        )

    # ------------------------------------------------------------------
    # Penarikan rentang
    # ------------------------------------------------------------------
    def test_rentang_menarik_beberapa_bulan_dan_menggabungkan_hasil(self):
        def fake_logs(params, _self=None):
            return {
                'data': [log_row(id=int(params['page']), work_date='2026-09-15')],
                'meta': {'total': 1, 'total_pages': 1},
            }

        def fake_recap(params, _self=None):
            return {
                'data': [recap_row(month=params['month'], attendance_count=1)],
                'meta': {'total': 1},
            }

        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=fake_logs), \
             patch.object(PresenlySaasClient, 'get_attendance_recap', side_effect=fake_recap), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=EMPTY_PAGE):
            summary, error = self.config._pull_period_range(9, 2026, months_back=3)

        self.assertFalse(error)
        self.assertEqual(summary['months'], 3)
        self.assertEqual(summary['periods'], ['07/2026', '08/2026', '09/2026'])
        self.assertEqual(summary['logs'], 3)
        self.assertEqual(summary['recap'], 3)

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

    def test_rentang_melaporkan_ketidakcocokan(self):
        def fake_logs(params, _self=None):
            return {'data': [log_row(id=1)], 'meta': {'total': 1, 'total_pages': 1}}

        def fake_recap(params, _self=None):
            # Server mengaku 5 sesi, cermin hanya punya 1.
            return {'data': [recap_row(month=params['month'], attendance_count=5)], 'meta': {}}

        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=fake_logs), \
             patch.object(PresenlySaasClient, 'get_attendance_recap', side_effect=fake_recap), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=EMPTY_PAGE):
            summary, error = self.config._pull_period_range(9, 2026, months_back=1)

        self.assertFalse(error)
        self.assertEqual(len(summary['mismatches']), 1)

    def test_rentang_melaporkan_hasil_terpotong(self):
        def fake_logs(params, _self=None):
            # Server punya 9999 baris, batas halaman membuat kita berhenti lebih awal.
            return {'data': [log_row(id=1)], 'meta': {'total': 9999, 'total_pages': 9999}}

        def fake_recap(params, _self=None):
            return {'data': [], 'meta': {}}

        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=fake_logs), \
             patch.object(PresenlySaasClient, 'get_attendance_recap', side_effect=fake_recap), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=EMPTY_PAGE):
            summary, _error = self.config._pull_period_range(9, 2026, months_back=1)

        self.assertTrue(summary['truncated'])

    def test_rentang_menolak_koneksi_nonaktif(self):
        self.config.write({'enabled': False})
        with self.assertRaises(UserError):
            self.config._pull_period_range(9, 2026, months_back=1)


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
             patch.object(PresenlySaasClient, 'get_attendance_recap', return_value=empty), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=empty):
            result = wizard.action_pull()

        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn('08/2026', result['params']['title'])
        self.assertIn('09/2026', result['params']['title'])
