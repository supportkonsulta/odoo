from datetime import date
from unittest.mock import patch

from odoo import _
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.saas_client import PresenlySaasClient, SaasClientError

EMPTY_PAGE = {'data': [], 'meta': {'total': 0, 'total_pages': 0}}


def leave_row(external_id, leave_date):
    return {
        'id': external_id,
        'reference_number': 'CT/%s' % external_id,
        'leave_date': leave_date,
        'status': 'approved',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
    }


def log_row(external_id, work_date):
    return {
        'id': external_id,
        'session_key': '%s:%s:default' % (external_id, work_date),
        'user_id': 2,
        'work_date': work_date,
        'status': 'closed',
        'late_minutes': 0,
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
    }


@tagged('post_install', '-at_install')
class TestPresenlyRetention(TransactionCase):
    """Jendela bergulir: yang tua dihapus, yang muda dan referensi dipertahankan."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)

    def setUp(self):
        super().setUp()
        self.config.write({'enabled': True, 'retention_months': 12})
        self.today = date.today()
        self.Log = self.env['presenly.saas.attendance.log']
        self.Leave = self.env['presenly.saas.leave']
        self.Log.search([]).unlink()
        self.Leave.search([]).unlink()

    def _hari(self, bulan_lalu):
        """Tanggal yang berjarak `bulan_lalu` bulan dari hari ini."""
        from dateutil.relativedelta import relativedelta
        return self.today - relativedelta(months=bulan_lalu)

    def test_batas_disimpan_hanya_bila_retensi_diisi(self):
        self.assertTrue(self.config._retention_cutoff())
        self.config.write({'retention_months': 0})
        self.assertFalse(self.config._retention_cutoff())

    def test_menghapus_log_dan_pengajuan_yang_tua(self):
        self.Log._upsert_rows(self.env.company, [
            log_row(1, str(self._hari(24))),
            log_row(2, str(self._hari(2))),
        ])
        self.Leave._mirror_replace(self.env.company, [
            leave_row(11, str(self._hari(18))),
            leave_row(12, str(self._hari(1))),
        ])

        removed = self.config._prune_mirrors()

        self.assertEqual(removed['presenly.saas.attendance.log'], 1)
        self.assertEqual(removed['presenly.saas.leave'], 1)
        self.assertEqual(self.Log.search_count([]), 1)
        self.assertEqual(self.Leave.search_count([]), 1)
        # Yang tersisa adalah yang masih di dalam jendela.
        self.assertEqual(self.Log.search([]).external_id, 2)
        self.assertEqual(self.Leave.search([]).external_id, 12)

    def test_tidak_menghapus_apa_pun_bila_semua_di_dalam_jendela(self):
        self.Log._upsert_rows(self.env.company, [
            log_row(1, str(self._hari(11))),
            log_row(2, str(self._hari(1))),
        ])

        removed = self.config._prune_mirrors()

        self.assertEqual(removed, {})
        self.assertEqual(self.Log.search_count([]), 2)

    def test_retensi_nol_menyimpan_semuanya(self):
        self.config.write({'retention_months': 0})
        self.Log._upsert_rows(self.env.company, [log_row(1, str(self._hari(60)))])

        removed = self.config._prune_mirrors()

        self.assertEqual(removed, {})
        self.assertEqual(self.Log.search_count([]), 1)

    def test_cermin_referensi_tidak_pernah_dihapus(self):
        self.env['presenly.saas.work.location']._mirror_replace(
            self.env.company,
            [{'id': 1, 'name': 'Lokasi Lama', 'is_active': True}],
        )
        self.config.write({'retention_months': 1})

        removed = self.config._prune_mirrors()

        self.assertNotIn('presenly.saas.work.location', removed)
        self.assertEqual(self.env['presenly.saas.work.location'].search_count([]), 1)

    def test_hanya_company_sendiri(self):
        lain = self.env['res.company'].create({'name': 'Perusahaan Lain'})
        self.Log._upsert_rows(lain, [log_row(99, str(self._hari(24)))])

        self.config._prune_mirrors()

        # Baris company lain tidak boleh ikut terhapus.
        self.assertEqual(self.Log.search_count([]), 1)


@tagged('post_install', '-at_install')
class TestPresenlyPullCron(TransactionCase):
    """Cron penarikan: jalan untuk koneksi aktif, tenang untuk yang lain."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)
        cls.Config = cls.env['presenly.saas.config']

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
            'api_key': 'k', 'retry_count': 0, 'pull_months': 2,
        })

    def test_menarik_sejumlah_bulan_dari_konfigurasi(self):
        terlihat = []

        def fake_resource(resource, params=None):
            terlihat.append((resource, params))
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource), \
             patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=EMPTY_PAGE):
            self.Config._cron_pull_periods_all()

        # Dua bulan x enam dataset berperiode (lima pengajuan + timesheet).
        self.assertEqual(len(terlihat), 12)

    def test_bulan_terakhir_selalu_ikut(self):
        terlihat = []

        def fake_resource(resource, params=None):
            terlihat.append(params)
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource), \
             patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=EMPTY_PAGE):
            self.Config._cron_pull_periods_all()

        bulan = {p['since'][:7] for p in terlihat}
        self.assertIn(date.today().strftime('%Y-%m'), bulan)

    def test_koneksi_nonaktif_tidak_dipanggil(self):
        self.config.write({'enabled': False})
        with patch.object(PresenlySaasClient, 'get_attendance_logs') as call:
            self.Config._cron_pull_periods_all()
        call.assert_not_called()

    def test_satu_tenant_gagal_tidak_menghentikan_yang_lain(self):
        lain = self.env['res.company'].create({'name': 'Perusahaan Lain'})
        kedua = self.Config._get_or_create(lain)
        kedua.write({
            'enabled': True, 'base_url': 'https://y', 'tenant_code': 'lain',
            'api_key': 'k2', 'retry_count': 0,
        })
        # Company pertama gagal, company kedua harus tetap ditarik.
        urutan = []

        def fake_pull(self, *_args, **_kwargs):
            urutan.append(self.company_id.name)
            if self.company_id == lain:
                return {'logs': 0, 'months': 1, 'submissions': {}}, 'gagal'
            return {'logs': 0, 'months': 1, 'submissions': {}}, False

        with patch.object(self.Config.__class__, '_pull_period_range', fake_pull):
            self.Config._cron_pull_periods_all()

        self.assertEqual(len(urutan), 2)

    def test_galat_koneksi_tidak_dilempar(self):
        gagal = SaasClientError('down', code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_attendance_logs', side_effect=gagal):
            # Tidak boleh melempar: satu tenant gagal bukan urusan tenant lain.
            self.assertTrue(self.Config._cron_pull_periods_all())

    def test_cron_pembersihan_mengembalikan_benar(self):
        self.assertTrue(self.Config._cron_prune_mirrors_all())


@tagged('post_install', '-at_install')
class TestPresenlyPeriodSettings(TransactionCase):
    """Setelan baru: batas nilai dan jembatan ke halaman Settings."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)

    def test_nilai_bawaan(self):
        self.assertEqual(self.config.pull_months, 2)
        self.assertEqual(self.config.retention_months, 12)

    def test_jumlah_bulan_minimal_satu(self):
        with self.assertRaises(Exception):
            self.env.cr.execute(
                "UPDATE presenly_saas_config SET pull_months = 0 WHERE id = %s",
                (self.config.id,),
            )

    def test_retensi_tidak_boleh_negatif(self):
        with self.assertRaises(Exception):
            self.env.cr.execute(
                "UPDATE presenly_saas_config SET retention_months = -1 WHERE id = %s",
                (self.config.id,),
            )

    def test_membaca_lewat_settings(self):
        self.config.write({'pull_months': 4, 'retention_months': 24})
        settings = self.env['res.config.settings'].create({})
        self.assertEqual(settings.presenly_saas_pull_months, 4)
        self.assertEqual(settings.presenly_saas_retention_months, 24)

    def test_menulis_lewat_settings(self):
        settings = self.env['res.config.settings'].create({
            'presenly_saas_pull_months': 3,
            'presenly_saas_retention_months': 6,
        })
        settings.execute()
        self.config.invalidate_recordset()
        self.assertEqual(self.config.pull_months, 3)
        self.assertEqual(self.config.retention_months, 6)

    def test_menulis_tidak_menghapus_kredensial(self):
        # Inverse per field: menyimpan satu setelan tidak boleh mengosongkan
        # tenant_code atau kunci API yang sedang dipakai.
        self.config.write({'tenant_code': 'iksg', 'api_key': 'rahasia'})
        settings = self.env['res.config.settings'].create({
            'presenly_saas_pull_months': 5,
        })
        settings.execute()
        self.config.invalidate_recordset()
        self.assertEqual(self.config.tenant_code, 'iksg')
        self.assertEqual(self.config.api_key, 'rahasia')


@tagged('post_install', '-at_install')
class TestPresenlyWizardRetentionNotice(TransactionCase):
    """Wizard memberi tahu kalau rentang yang diminta lebih tua dari batas simpan."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)
        cls.Wizard = cls.env['presenly.saas.pull.wizard']

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
            'api_key': 'k', 'retry_count': 0,
        })

    def _tarik(self, months_back, retention):
        self.config.write({'retention_months': retention})
        today = date.today()
        wizard = self.Wizard.create({
            'month': str(today.month), 'year': today.year, 'months_back': months_back,
        })
        with patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=EMPTY_PAGE), \
             patch.object(PresenlySaasClient, 'get_resource', return_value=EMPTY_PAGE):
            return wizard.action_pull()

    def _pesan_batas_simpan(self, months):
        """Peringatan yang diharapkan, dari string sumber yang sama.

        Dibangun begini supaya tes tidak bergantung bahasa pengguna, dan tetap
        gagal kalau pesannya ditulis langsung sehingga tidak bisa diterjemahkan.
        """
    # Memakai `_()` polos, bukan `self.env._()`, karena modul ini memakai yang
    # polos. Di lingkungan tes `env.lang` bernilai kosong, sehingga
    # `self.env._()` mengembalikan teks sumber apa adanya, sementara `_()`
    # mengikuti bahasa pengguna seperti di produksi. Memakai mekanisme yang
    # sama membuat tes lulus di bahasa mana pun, dan tetap gagal kalau pesannya
    # ditulis langsung sehingga tidak bisa diterjemahkan.
        return _(
            "Part of this range is older than the retention window "
            "(%(months)s months). The weekly cleanup will remove it "
            "again; raise Retention in Settings to keep it.",
            months=months,
        )

    def test_memberi_tahu_bila_rentang_melewati_batas_simpan(self):
        result = self._tarik(months_back=24, retention=12)
        self.assertEqual(result['params']['type'], 'warning')
        self.assertIn(self._pesan_batas_simpan(12), result['params']['message'])

    def test_tidak_memberi_tahu_bila_masih_di_dalam_batas(self):
        result = self._tarik(months_back=2, retention=12)
        self.assertEqual(result['params']['type'], 'success')
        self.assertNotIn(self._pesan_batas_simpan(12), result['params']['message'])

    def test_tidak_memberi_tahu_bila_semua_disimpan(self):
        result = self._tarik(months_back=24, retention=0)
        self.assertEqual(result['params']['type'], 'success')
        self.assertNotIn(self._pesan_batas_simpan(0), result['params']['message'])


@tagged('post_install', '-at_install')
class TestPresenlyRangeReplaceIsAtomic(TransactionCase):
    """Penggantian per rentang tidak boleh menghapus tanpa sempat menulis.

    Urutannya memang hapus dulu, baru tulis — baris lama memakai `external_id`
    yang sama, jadi menulis lebih dulu akan menabrak constraint-nya. Yang dijaga
    di sini adalah kegagalan di tengah: penghapusan yang sudah berjalan tidak
    boleh ikut ter-commit sendirian, karena hasilnya adalah data yang hilang
    tanpa penggantinya dan tanpa catatan gagal — persis yang membuat daftar cuti
    tampak kosong walaupun server masih memegang datanya.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)

    def setUp(self):
        super().setUp()
        self.Leave = self.env['presenly.saas.leave']
        self.Leave.search([]).unlink()

    def _replace(self, rows):
        return self.Leave._mirror_replace_range(
            self.env.company, rows, date(2026, 9, 1), date(2026, 9, 30),
        )

    def test_penulisan_yang_gagal_tidak_menghapus_baris_lama(self):
        self.assertEqual(self._replace([leave_row(1, '2026-09-10')]), 1)
        self.assertEqual(self.Leave.search_count([]), 1)

        with patch.object(type(self.Leave), 'create', side_effect=ValueError('gagal')):
            with self.assertRaises(ValueError):
                self._replace([leave_row(2, '2026-09-11')])

        self.assertEqual(
            self.Leave.search_count([]), 1,
            'baris lama tidak boleh ikut terhapus',
        )
        self.assertEqual(self.Leave.search([]).external_id, 1)

    def test_penulisan_yang_berhasil_tetap_mengganti(self):
        self._replace([leave_row(1, '2026-09-10')])

        self.assertEqual(self._replace([leave_row(2, '2026-09-11')]), 1)

        self.assertEqual(self.Leave.search_count([]), 1)
        self.assertEqual(self.Leave.search([]).external_id, 2)
