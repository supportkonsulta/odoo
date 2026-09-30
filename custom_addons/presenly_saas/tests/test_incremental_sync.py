from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.saas_client import PresenlySaasClient, SaasClientError

EMPTY_PAGE = {'data': [], 'meta': {'total': 0, 'total_pages': 0}}


def halaman(rows, server_time='2026-09-23T02:00:00.000Z'):
    return {
        'data': rows,
        'meta': {'total': len(rows), 'total_pages': 1, 'server_time': server_time},
    }


def leave_row(**overrides):
    row = {
        'id': 201,
        'reference_number': 'CT/2026/00201',
        'leave_date': '2026-09-23',
        'start_date': '2026-09-24',
        'end_date': '2026-09-24',
        'total_days': 1.0,
        'status': 'pending',
        'created_at': '2026-09-23T01:00:00.000Z',
        'updated_at': '2026-09-23T01:30:00.000Z',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
    }
    row.update(overrides)
    return row


class SyncTestBase(TransactionCase):
    """Dasar bersama: koneksi aktif, cermin kosong, log kosong."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Leave = cls.env['presenly.saas.leave']
        cls.Mark = cls.env['presenly.saas.sync.mark']
        cls.Log = cls.env['presenly.saas.sync.log']

    def setUp(self):
        super().setUp()
        self.Leave.search([]).unlink()
        self.Mark.search([]).unlink()
        self.Log.search([]).unlink()
        self.config.write({
            'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
            'api_key': 'k', 'retry_count': 0, 'request_auto_refresh': True,
        })

    def _tarik(self, peta):
        """Jalankan penarikan tambahan dengan klien yang dipalsukan.

        `peta` dikunci dengan nama resource terakhir di pathnya
        (`'leaves'`, `'attendance-logs'`, …).
        """
        dicatat = []

        def palsu(path, params=None):
            dicatat.append((path, params or {}))
            hasil = peta.get(path.rsplit('/', 1)[-1], EMPTY_PAGE)
            if isinstance(hasil, Exception):
                raise hasil
            return hasil

        with patch.object(PresenlySaasClient, 'get_envelope', side_effect=palsu):
            summary, error = self.config._pull_recent_data()
        return summary, error, dicatat

    def _segar(self):
        """Jalankan penyegaran seperti dari halaman, di transaksi tes ini.

        Yang diuji di kelas-kelas di bawah adalah logikanya. Jalur halaman yang
        sebenarnya — transaksi tersendiri yang di-commit — diuji sekali di
        `TestPresenlyRefreshOnOpen`, dan itu memang menulis permanen ke database
        uji; karena itu hanya satu tes yang menempuhnya.
        """
        return self.config._refresh_requests_now(self.config.id)


@tagged('post_install', '-at_install')
class TestPresenlyIncrementalPull(SyncTestBase):
    """Penarikan tambahan: yang berubah sejak penanda terakhir.

    Penarikan rentang menyaring **tanggal bisnis** pengajuannya, sehingga koreksi
    presensi untuk bulan lalu atau tukar shift untuk bulan depan tidak pernah ikut
    terambil. Penarikan tambahan menyaring `updated_at`, jadi yang menentukan
    hanyalah kapan barisnya berubah.
    """

    def test_baris_baru_ditambahkan(self):
        summary, error, _ = self._tarik({'leaves': halaman([leave_row()])})
        self.assertFalse(error)
        self.assertEqual(summary['datasets']['leaves'], 1)
        self.assertEqual(self.Leave.search_count([]), 1)

    def test_penarikan_tambahan_tidak_menghapus_baris_lain(self):
        # Baris dari bulan lain tidak ikut terambil, tetapi bukan berarti basi.
        self.Leave.create({
            'company_id': self.company.id, 'external_id': 999,
            'reference_number': 'CT/2026/00999', 'leave_date': '2026-08-01',
        })
        self._tarik({'leaves': halaman([leave_row()])})
        self.assertEqual(self.Leave.search_count([]), 2)
        self.assertTrue(self.Leave.search([('external_id', '=', 999)]))

    def test_baris_yang_sama_diperbarui_bukan_diduplikasi(self):
        self._tarik({'leaves': halaman([leave_row(status='pending')])})
        self._tarik({'leaves': halaman([leave_row(status='approved')])})

        self.assertEqual(self.Leave.search_count([]), 1)
        self.assertEqual(self.Leave.search([]).status, 'approved')

    def test_langkah_persetujuan_tidak_menumpuk(self):
        # Tanpa penulisan ulang baris anak, setiap penarikan tambahan menambah
        # satu set level baru di atas yang lama.
        blok = {
            'has_workflow': True, 'status': 'pending', 'current_level': 2,
            'total_levels': 2,
            'steps': [
                {'level': 1, 'status': 'approved',
                 'expected': {'type': 'direct_manager'},
                 'acted_by': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
                 'acted_at': '2026-09-22T02:15:00.000Z'},
                {'level': 2, 'status': 'pending',
                 'expected': {'type': 'role', 'value': 'hrd'}},
            ],
        }
        for _ulang in range(3):
            self._tarik({'leaves': halaman([leave_row(approval=blok)])})

        cuti = self.Leave.search([])
        self.assertEqual(len(cuti), 1)
        self.assertEqual(len(cuti.approval_step_ids), 2)

    # ------------------------------------------------------------------
    # Yang menentukan: waktu perubahan, bukan tanggal bisnis
    # ------------------------------------------------------------------
    def test_pengajuan_bertanggal_lama_tetap_tertarik(self):
        # Koreksi presensi untuk bulan lalu, atau tukar shift untuk bulan depan,
        # tidak pernah masuk lewat penarikan rentang. Lewat `updated_since`, yang
        # dibandingkan adalah kapan barisnya berubah.
        bulan_lalu = leave_row(leave_date='2026-08-05', start_date='2026-08-06')
        self._tarik({'leaves': halaman([bulan_lalu])})
        self.assertEqual(self.Leave.search_count([]), 1)
        self.assertEqual(self.Leave.search([]).leave_date, datetime(2026, 8, 5).date())

    def test_penarikan_kedua_memakai_waktu_perubahan(self):
        _summary, _error, pertama = self._tarik({'leaves': halaman([leave_row()])})
        path_cuti = '/v1/leaves'
        self.assertNotIn('updated_since', dict(pertama)[path_cuti],
                         'penarikan pertama belum punya penanda')

        _summary, _error, kedua = self._tarik({'leaves': halaman([])})
        dikirim = dict(kedua)[path_cuti]['updated_since']
        self.assertTrue(dikirim.endswith('Z'), 'bukan ISO-8601 UTC: %s' % dikirim)
        # Tumpang tindih beberapa menit dipakai sengaja: API menyaring dengan
        # `>`, jadi baris yang berubah pada detik yang sama bisa terlewat.
        self.assertLess(dikirim, '2026-09-23T02:00:00Z')

    def test_penanda_memakai_waktu_server(self):
        self._tarik({'leaves': halaman([leave_row()], server_time='2026-09-23T02:00:00.000Z')})
        mark = self.Mark.search([('dataset', '=', 'leaves')])
        self.assertEqual(mark.last_synced_at, datetime(2026, 9, 23, 2, 0, 0))

    # ------------------------------------------------------------------
    # Kegagalan
    # ------------------------------------------------------------------
    def test_kegagalan_dikembalikan_sebagai_nilai(self):
        gagal = SaasClientError('down', code='NETWORK_ERROR')
        _summary, error, _ = self._tarik({'leaves': gagal})
        self.assertTrue(error)

    def test_penanda_tidak_maju_saat_gagal(self):
        # Kalau penanda tetap maju, perubahan pada jenis itu terlewat selamanya.
        gagal = SaasClientError('down', code='NETWORK_ERROR')
        self._tarik({'leaves': gagal})
        self.assertFalse(self.Mark.search([('dataset', '=', 'leaves')]))
        self.assertFalse(self.Mark.search([('dataset', '=', 'overtimes')]))

    # ------------------------------------------------------------------
    # Cakupan
    # ------------------------------------------------------------------
    def test_mencakup_presensi_dan_timesheet_juga(self):
        # Dulu hanya pengajuan, dan itu sebabnya absensi baru dari aplikasi tidak
        # pernah muncul selama presensi belum ikut ditarik tambahan.
        _summary, _error, dicatat = self._tarik({})
        # Path yang dikirim ke klien relatif ke akar API: klien menambahkan
        # `/api/external` sendiri.
        path = [satu_path for satu_path, _params in dicatat]
        self.assertIn('/v1/presenly/attendance-logs', path)
        self.assertIn('/v1/timesheets', path)
        for resource in ('leaves', 'overtimes', 'medical-certificates',
                         'attendance-corrections', 'shift-swaps'):
            self.assertIn('/v1/%s' % resource, path)


@tagged('post_install', '-at_install')
class TestPresenlyRefreshGuard(SyncTestBase):
    """Penjagaan waktu: jangan menarik kalau baru saja ditarik, dan jangan dua kali."""

    def _catat_percobaan(self, detik_lalu=0):
        """Catat percobaan penarikan yang terjadi `detik_lalu` detik yang lalu.

        `create_date` adalah field sihir: nilainya tidak bisa diberikan lewat
        `create`, jadi diubah langsung di database.
        """
        log = self.Log.create({
            'company_id': self.company.id,
            'endpoint': '/api/external/v1/leaves',
            'success': True,
            'http_status': 200,
        })
        self.env.cr.execute(
            'UPDATE presenly_saas_sync_log SET create_date = %s WHERE id = %s',
            [fields.Datetime.now() - timedelta(seconds=detik_lalu), log.id],
        )
        log.invalidate_recordset()

    def _ubah(self, **waktu):
        """Klien tiruan: `changes` menjawab waktu tertentu, sisanya kosong."""
        dicatat = []

        def envelope(path, params=None):
            dicatat.append(path)
            if path == '/v1/presenly/changes':
                return {'data': dict(waktu), 'meta': {'server_time': '2026-09-23T03:00:00.000Z'}}
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_envelope', side_effect=envelope):
            dijalankan = self._segar()
        return dijalankan, dicatat

    def test_tidak_ada_yang_berubah_berarti_tidak_menarik(self):
        # Ini yang paling sering terjadi, dan harus murah: satu permintaan.
        dijalankan, dicatat = self._ubah(leaves=None, overtimes=None)
        self.assertFalse(dijalankan)
        self.assertEqual(dicatat, ['/v1/presenly/changes'])

    def test_yang_berubah_saja_yang_ditarik(self):
        dijalankan, dicatat = self._ubah(
            leaves='2026-09-23T02:44:48.000Z', overtimes=None,
            **{'attendance-logs': None},
        )
        self.assertTrue(dijalankan)
        self.assertIn('/v1/leaves', dicatat)
        self.assertNotIn('/v1/overtimes', dicatat)

    def test_jenis_tanpa_penanda_ikut_ditarik(self):
        # Belum pernah ditarik: apa pun isinya perlu ditarik.
        dijalankan, dicatat = self._ubah(leaves='2026-09-23T02:44:48.000Z')
        self.assertTrue(dijalankan)
        self.assertIn('/v1/leaves', dicatat)

    def test_pemeriksaan_yang_gagal_tidak_menarik_apa_pun(self):
        gagal = SaasClientError('down', code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_envelope', side_effect=gagal):
            dijalankan = self._segar()
        self.assertFalse(dijalankan)

    def test_bisa_dimatikan(self):
        self.config.request_auto_refresh = False
        with patch.object(PresenlySaasClient, 'get_envelope') as palsu:
            dijalankan = self._segar()
        self.assertFalse(dijalankan)
        palsu.assert_not_called()

    def test_koneksi_nonaktif_tidak_menarik_apa_pun(self):
        self.config.enabled = False
        with patch.object(PresenlySaasClient, 'get_envelope') as palsu:
            dijalankan = self._segar()
        self.assertFalse(dijalankan)
        palsu.assert_not_called()

    def test_referensi_tidak_ditarik_berulang(self):
        # Referensi jarang berubah, jadi ambangnya sendiri: sejam. Penarikan
        # berikutnya dalam rentang itu tidak menyentuhnya lagi.
        referensi = []

        def palsu_resource(resource, params=None):
            referensi.append(resource)
            return EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_envelope', return_value=EMPTY_PAGE), \
             patch.object(PresenlySaasClient, 'get_resource', side_effect=palsu_resource):
            self.config._pull_recent_data()
            pertama = len(referensi)
            self.config._pull_recent_data()
            kedua = len(referensi)

        self.assertTrue(pertama, 'referensi belum pernah ditarik')
        self.assertEqual(kedua, pertama, 'referensi ditarik lagi padahal belum sejam')

    def test_presensi_tidak_ikut_menyegarkan_diri(self):
        # Presensi sengaja tidak memakai pemicu ini: tabelnya besar, dan
        # penarikan rentang menulis ulang seluruh rentangnya.
        self.assertNotIn(
            '_presenly_refresh_requests', dir(self.env['presenly.saas.attendance.log']),
            'cermin presensi ikut memakai pemicu penyegaran dari halaman',
        )


@tagged('post_install', '-at_install')
class TestPresenlyRefreshOnOpen(SyncTestBase):
    """Jalur halaman yang sebenarnya: satu tes, dan ia menulis permanen."""

    def test_membuka_daftar_memicu_penyegaran(self):
        """Sambungannya yang diperiksa di sini, bukan logikanya.

        Penyegaran berjalan di transaksi tersendiri — itu yang membuatnya bisa
        menulis dari pembacaan yang ditandai `@api.readonly`. Konsekuensinya, ia
        juga tidak bisa melihat data yang belum di-commit milik tes ini, sehingga
        hasilnya tidak bisa diperiksa dari dalam tes. Logikanya diuji langsung di
        `TestPresenlyRefreshGuard`, dan sambungan ujung-ke-ujungnya diperiksa di
        browser terhadap server Presenly yang sebenarnya.
        """
        with patch.object(type(self.env['presenly.saas.config']), '_refresh_from_page') \
                as segarkan:
            self.Leave.web_search_read([], {'display_name': {}})
        segarkan.assert_called()

    def test_halaman_tetap_terbuka_saat_server_tidak_bisa_dihubungi(self):
        gagal = SaasClientError('down', code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_resource', side_effect=gagal):
            hasil = self.Leave.web_search_read([], {'display_name': {}})
        self.assertIn('records', hasil)

    def test_galat_yang_tidak_terduga_pun_tidak_menggagalkan_halaman(self):
        with patch.object(PresenlySaasClient, 'get_resource',
                          side_effect=ValueError('bentuk respons aneh')):
            hasil = self.Leave.web_search_read([], {'display_name': {}})
        self.assertIn('records', hasil)


@tagged('post_install', '-at_install')
class TestPresenlyPullEntryPoint(SyncTestBase):
    """Wizard penarikan harus bisa dijangkau dari antarmuka."""

    def test_action_wizard_ada(self):
        action = self.env.ref('presenly_saas.action_presenly_saas_pull_period')
        self.assertEqual(action.res_model, 'presenly.saas.pull.wizard')
        self.assertEqual(action.target, 'new')

    def test_tombolnya_ada_di_form_subscription(self):
        # Di arch yang sudah diproses, rujukan action menjadi angka; yang
        # diperiksa adalah tombolnya ada dan actionnya benar-benar bisa dibuka.
        action = self.env.ref('presenly_saas.action_presenly_saas_pull_period')
        arch = self.env['presenly.saas.subscription'].get_view(view_type='form')['arch']
        self.assertIn('name="%s"' % action.id, arch)
        self.assertIn('Pull Period Data', arch)

    def test_wizard_bisa_dijalankan(self):
        wizard = self.env['presenly.saas.pull.wizard'].create({
            'config_id': self.config.id, 'month': '9', 'year': 2026, 'months_back': 1,
        })

        def palsu(resource, params=None):
            return halaman([leave_row()]) if resource == 'leaves' else EMPTY_PAGE

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=palsu), \
             patch.object(PresenlySaasClient, 'get_attendance_logs', return_value=EMPTY_PAGE):
            wizard.action_pull()

        self.assertTrue(self.Leave.search_count([]))

    def test_wizard_menolak_koneksi_nonaktif(self):
        self.config.enabled = False
        wizard = self.env['presenly.saas.pull.wizard'].create({
            'config_id': self.config.id, 'month': '9', 'year': 2026, 'months_back': 1,
        })
        with self.assertRaises(UserError):
            wizard.action_pull()


@tagged('post_install', '-at_install')
class TestPresenlySyncSettings(SyncTestBase):
    """Setelan penyegaran, dan kenapa ia pernah mematikan dirinya sendiri.

    Halaman Settings memakai field compute/inverse. Kalau compute-nya tidak
    mengisi fieldnya, halaman itu menampilkan nilai kosong — dan menyimpannya
    menulis nilai kosong itu kembali ke konfigurasi. Penyegaran otomatisnya mati
    tanpa satu pun pesan kesalahan, dan satu-satunya gejalanya data yang tidak
    muncul. Tes ini mengunci putaran tampil→simpan itu.
    """

    def test_halaman_settings_menampilkan_nilai_yang_berlaku(self):
        self.config.request_auto_refresh = True
        settings = self.env['res.config.settings'].create({})
        self.assertTrue(settings.presenly_saas_request_auto_refresh)

    def test_menyimpan_settings_tidak_mematikan_penyegaran(self):
        self.config.request_auto_refresh = True
        settings = self.env['res.config.settings'].create({})
        settings.write({'presenly_saas_request_auto_refresh': True})
        self.assertTrue(self.config.request_auto_refresh)

    def test_mematikan_penyegaran_masih_bisa_dipilih(self):
        settings = self.env['res.config.settings'].create({})
        settings.write({'presenly_saas_request_auto_refresh': False})
        self.assertFalse(self.config.request_auto_refresh)

    def test_mematikan_cron_mematikan_cronnya(self):
        settings = self.env['res.config.settings'].create({})
        settings.write({'presenly_saas_cron_sync_minutes': 0})
        cron = self.env.ref('presenly_saas.ir_cron_presenly_saas_sync_recent')
        self.assertFalse(cron.active)

    def test_menyalakan_cron_menulis_iramanya(self):
        settings = self.env['res.config.settings'].create({})
        settings.write({'presenly_saas_cron_sync_minutes': 30})
        cron = self.env.ref('presenly_saas.ir_cron_presenly_saas_sync_recent')
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_number, 30)
        self.assertEqual(cron.interval_type, 'minutes')
