"""Gerbang langganan: fungsi keputusannya, dan kebijakan di sekitarnya.

Dua lapis diuji terpisah, dan itu disengaja:

1. `decide_block()` adalah fungsi murni. Seluruh matriks keadaan diuji tanpa
   basis data dan tanpa HTTP, jadi tiap baris aturannya terbaca sebagai satu
   baris tes.
2. `request_block_reason()` adalah kebijakan: jalur, peran, sekoci, dan mode.
   Yang diuji di sini adalah urutannya, termasuk hal yang TIDAK boleh diblokir.

Jalur HTTP-nya sendiri diuji di `test_guard_http.py`.
"""

from datetime import datetime, timedelta
from unittest import mock

from odoo import SUPERUSER_ID, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..controllers.blocked import PresenlySaasBlocked
from ..models.presenly_saas_guard import FORCE_ALLOW_PARAM, decide_block

NOW = datetime(2026, 9, 28, 12, 0, 0)


def facts(**overrides):
    """Fakta yang tidak memblokir, supaya tiap tes hanya menyebut yang diubah."""
    base = {
        'block_mode': 'enforce',
        'grace_days': 7,
        'override_until': False,
        'status': 'active',
        'state_source': 'live',
        'is_trial': False,
        'trial_ends_at': False,
        'current_period_end': NOW + timedelta(days=30),
        'last_sync_at': NOW,
        'dry_run_noted_at': False,
        'blocked_since': False,
    }
    base.update(overrides)
    return base


@tagged('post_install', '-at_install')
class TestPresenlyBlockDecision(TransactionCase):
    """Matriks keadaan, tanpa basis data."""

    # ------------------------------------------------------------------
    # Jawaban nyata dari server
    # ------------------------------------------------------------------
    def test_langganan_aktif_tidak_memblokir(self):
        self.assertFalse(decide_block(facts(), NOW))

    def test_kedaluwarsa_memblokir(self):
        self.assertEqual(decide_block(facts(status='expired'), NOW), 'expired')

    def test_ditangguhkan_memblokir(self):
        self.assertEqual(decide_block(facts(status='suspended'), NOW), 'suspended')

    def test_tanpa_fakta_tidak_memblokir(self):
        self.assertFalse(decide_block({}, NOW))
        self.assertFalse(decide_block(None, NOW))

    def test_status_tak_dikenal_tidak_memblokir(self):
        """Status ditentukan server. Modul ini tidak menebak."""
        self.assertFalse(decide_block(facts(status='unknown'), NOW))

    # ------------------------------------------------------------------
    # Masa uji
    # ------------------------------------------------------------------
    def test_masa_uji_yang_sudah_lewat_memblokir(self):
        hasil = decide_block(facts(
            status='trial', is_trial=True,
            trial_ends_at=NOW - timedelta(days=1),
        ), NOW)
        self.assertEqual(hasil, 'trial_ended')

    def test_masa_uji_yang_masih_berjalan_tidak_memblokir(self):
        self.assertFalse(decide_block(facts(
            status='trial', is_trial=True,
            trial_ends_at=NOW + timedelta(days=10),
        ), NOW))

    # ------------------------------------------------------------------
    # Snapshot yang tidak dikonfirmasi
    # ------------------------------------------------------------------
    def test_jawaban_lama_yang_negatif_tidak_memblokir(self):
        """Hanya jawaban nyata yang memblokir.

        Status `expired` yang datang dari jawaban lama tidak boleh menutup
        akses selama tenggangnya belum lewat: yang gagal adalah konfirmasinya,
        bukan langganannya.
        """
        self.assertFalse(decide_block(facts(
            status='expired', state_source='cached',
            last_sync_at=NOW - timedelta(days=1),
        ), NOW))

    def test_tidak_terkonfirmasi_melewati_tenggang_memblokir(self):
        self.assertEqual(decide_block(facts(
            status='expired', state_source='cached',
            last_sync_at=NOW - timedelta(days=8),
        ), NOW), 'unconfirmed')

    def test_tidak_terkonfirmasi_di_dalam_tenggang_tidak_memblokir(self):
        self.assertFalse(decide_block(facts(
            status='expired', state_source='cached',
            last_sync_at=NOW - timedelta(days=3),
        ), NOW))

    def test_tenggang_nol_mematikan_bagian_luring(self):
        """Bawaan fail-open: jaringan putus tidak pernah mengunci siapa pun."""
        self.assertFalse(decide_block(facts(
            status='expired', state_source='unreachable', grace_days=0,
            last_sync_at=NOW - timedelta(days=365),
        ), NOW))

    def test_belum_pernah_dikonfirmasi_tidak_memblokir(self):
        """Tanpa satu pun jawaban, tidak ada dasar untuk menutup apa pun."""
        self.assertFalse(decide_block(facts(
            status=False, state_source='unreachable', last_sync_at=False,
        ), NOW))

    def test_status_aktif_yang_lama_juga_memblokir(self):
        """Yang tidak bisa dipercaya bukan hanya kabar buruk."""
        self.assertEqual(decide_block(facts(
            status='active', state_source='cached',
            last_sync_at=NOW - timedelta(days=30),
        ), NOW), 'unconfirmed')

    # ------------------------------------------------------------------
    # Mode dan akses sementara
    # ------------------------------------------------------------------
    def test_mode_bukan_urusan_fungsi_murni(self):
        """Mode adalah kebijakan, dan dipasang pemanggilnya.

        `decide_block()` hanya membaca fakta. Yang memutuskan apakah fakta itu
        ditegakkan adalah `block_reason()` dan `request_block_reason()`; itu
        yang diuji di kelas kebijakan di bawah.
        """
        self.assertEqual(decide_block(
            facts(status='expired', block_mode='off'), NOW
        ), 'expired')

    def test_akses_sementara_menahan_blokir(self):
        self.assertFalse(decide_block(facts(
            status='expired', override_until=NOW + timedelta(days=2),
        ), NOW))

    def test_akses_sementara_yang_lewat_tidak_menahan(self):
        self.assertEqual(decide_block(facts(
            status='expired', override_until=NOW - timedelta(minutes=1),
        ), NOW), 'expired')


@tagged('post_install', '-at_install')
class TestPresenlyGatePolicy(TransactionCase):
    """Kebijakan gerbang di atas fakta: jalur, peran, sekoci, dan mode.

    Gerbangnya selalu dipanggil sebagai pengguna internal biasa, bukan sebagai
    superuser: lingkungan tes Odoo berjalan sebagai uid 1, dan uid 1 memang
    sengaja selalu diloloskan sebagai jalan pemulihan. Menguji tanpa `with_user`
    berarti menguji sekocinya, bukan gerbangnya.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.guard = cls.env['presenly.saas.guard'].with_user(
            cls.env.ref('base.user_admin')
        )
        cls.Subscription = cls.env['presenly.saas.subscription']

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True,
            'base_url': 'https://saas.example.com',
            'tenant_code': 'demo',
            'api_key': 'secret-key',
            'guard_mode': 'enforce',
            'grace_days': 7,
            'block_mode': 'enforce',
            'block_override_until': False,
            'block_override_reason': False,
            'blocked_since': False,
        })
        self.Subscription.search([]).unlink()
        self.env['ir.config_parameter'].sudo().set_param(FORCE_ALLOW_PARAM, '')

    def snapshot(self, status='expired', **overrides):
        data = {
            'status': status,
            'tenant_code': 'demo',
            'client_name': 'Tenant Uji',
            'current_period_end': fields.Datetime.now() + timedelta(days=30),
        }
        data.update(overrides)
        return self.Subscription._sync_from_payload(self.config, data)

    # ------------------------------------------------------------------
    # Jalur yang tetap hidup
    # ------------------------------------------------------------------
    def test_jalur_yang_diizinkan_tidak_pernah_diblokir(self):
        """Aset dan halaman masuk harus hidup, atau tidak ada cara memperbaiki."""
        self.snapshot(status='expired')
        self.assertEqual(self.guard.request_block_reason('/odoo'), 'expired',
                         'prasyarat: backend memang ditutup')
        for path in (
            '/web/assets/abc/web.assets_web.min.js',
            '/web/static/img/favicon.ico',
            '/web/login',
            '/web/session/get_session_info',
            '/web/manifest.webmanifest',
            '/web/binary/company_logo',
            '/logo.png',
            '/favicon.ico',
            '/presenly_saas/blocked',
            '/presenly_saas/blocked/refresh',
            '/presenly_saas/webhook/token-uji',
        ):
            with self.subTest(path=path):
                self.assertFalse(self.guard.request_block_reason(path), path)

    def test_permintaan_aset_tidak_menambah_baca(self):
        """Jalur aset diperiksa sebelum basis data disentuh."""
        self.snapshot(status='expired')
        with self.assertQueryCount(0):
            self.guard.request_block_reason('/web/assets/abc/file.js')

    def test_biaya_gerbang_pada_jalur_biasa(self):
        """Anggaran pembacaan gerbang: empat pembacaan berindeks.

        Rinciannya dua model, dan ORM menagih dua query untuk masing-masing
        (satu pencarian, satu pembacaan kolom): konfigurasi dan snapshot. Angka
        ini yang menggantikan rencana cache di `PLAN_GLOBAL_GUARD.md`: empat
        pembacaan langsung lebih murah daripada membuang cache inti Odoo setiap
        kali langganan disegarkan, dan lebih mudah dipercaya karena tidak ada
        jawaban basi yang perlu diinvalidasi.

        Dikunci di sini supaya penambahan query tanpa sadar langsung terlihat.
        Permintaan pertama untuk seorang pengguna membayar lebih banyak (grup,
        aturan), dan itu biaya satu kali per pengguna, bukan biaya gerbangnya.
        """
        self.snapshot(status='expired')
        self.guard.request_block_reason('/odoo')
        with self.assertQueryCount(4):
            self.guard.request_block_reason('/odoo')

    # ------------------------------------------------------------------
    # Yang ditolak
    # ------------------------------------------------------------------
    def test_backend_ditolak_saat_langganan_hangus(self):
        self.snapshot(status='expired')
        self.assertEqual(self.guard.request_block_reason('/odoo'), 'expired')
        self.assertEqual(
            self.guard.request_block_reason('/web/dataset/call_kw'), 'expired',
        )
        self.assertEqual(
            self.guard.request_block_reason('/report/pdf/sale.report/1'), 'expired',
        )
        self.assertEqual(
            self.guard.request_block_reason('/api/presenly/v1/attendance/status'),
            'expired',
        )

    def test_manajer_ikut_ditolak_di_backend(self):
        """Yang dibuka untuk manajer adalah halaman blokir, bukan backend.

        Kalau manajer bisa masuk, penutupannya hanya soal tahu atau tidak tahu
        URL, dan itu bukan penutupan.
        """
        self.snapshot(status='expired')
        self.assertTrue(
            self.guard.env.user.has_group('presenly_saas.group_presenly_saas_manager')
        )
        self.assertEqual(self.guard.request_block_reason('/odoo'), 'expired')

    def test_mode_off_dan_dry_run_meloloskan_backend(self):
        for mode in ('off', 'dry_run'):
            with self.subTest(mode=mode):
                self.config.block_mode = mode
                self.snapshot(status='expired')
                self.assertFalse(self.guard.request_block_reason('/odoo'))

    def test_uji_coba_menghitung_tanpa_memblokir(self):
        self.config.write({'block_mode': 'dry_run', 'dry_run_blocked_count': 0})
        self.snapshot(status='expired')

        for _ in range(5):
            self.assertFalse(self.guard.request_block_reason('/odoo'))

        # Dihitung paling banyak sekali semenit: angka ini perkiraan besar,
        # bukan hitungan per permintaan, dan itu disebutkan di halaman setelan.
        self.assertEqual(self.config.dry_run_blocked_count, 1)

    def test_uji_coba_tidak_dihitung_saat_langganan_sehat(self):
        self.config.write({'block_mode': 'dry_run', 'dry_run_blocked_count': 0})
        self.snapshot(status='active')
        self.assertFalse(self.guard.request_block_reason('/odoo'))
        self.assertEqual(self.config.dry_run_blocked_count, 0)

    def test_akses_sementara_meloloskan_backend(self):
        self.snapshot(status='expired')
        self.config.write({
            'block_override_until': fields.Datetime.now() + timedelta(days=1),
            'block_override_reason': 'perpanjangan sedang diproses',
        })
        self.assertFalse(self.guard.request_block_reason('/odoo'))

    # ------------------------------------------------------------------
    # Sekoci
    # ------------------------------------------------------------------
    def test_sekoci_dari_config_parameter(self):
        self.snapshot(status='expired')
        self.env['ir.config_parameter'].sudo().set_param(FORCE_ALLOW_PARAM, '1')
        self.assertFalse(self.guard.request_block_reason('/odoo'))

    def test_context_skip_guard_meloloskan(self):
        self.snapshot(status='expired')
        guard = self.guard.with_context(presenly_saas_skip_guard=True)
        self.assertFalse(guard.request_block_reason('/odoo'))
        self.assertFalse(guard.block_reason())

    def test_superuser_selalu_lolos(self):
        self.snapshot(status='expired')
        guard = self.guard.with_user(SUPERUSER_ID)
        self.assertFalse(guard.request_block_reason('/odoo'))

    def test_portal_dan_publik_tidak_ikut_ditutup(self):
        """Mereka pelanggan tenant, bukan stafnya."""
        self.snapshot(status='expired')
        portal = self.env['res.users'].create({
            'name': 'Portal Uji',
            'login': 'portal.uji.presenly',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.assertFalse(
            self.guard.with_user(portal).request_block_reason('/my/invoices')
        )

    def test_pengguna_internal_biasa_ditolak(self):
        """Kebalikan dari dua tes di atas: yang ditutup adalah staf tenant."""
        self.snapshot(status='expired')
        staf = self.env['res.users'].create({
            'name': 'Staf Uji',
            'login': 'staf.uji.presenly',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.assertEqual(
            self.guard.with_user(staf).request_block_reason('/odoo'), 'expired'
        )

    # ------------------------------------------------------------------
    # Pencatatan
    # ------------------------------------------------------------------
    def test_blokir_ditandai_sekali(self):
        self.snapshot(status='expired')
        self.guard.request_block_reason('/odoo')
        pertama = self.config.blocked_since
        self.assertTrue(pertama, 'blokir mulai ditandai')

        self.guard.request_block_reason('/odoo')
        self.assertEqual(self.config.blocked_since, pertama, 'tidak ditandai ulang')

    def test_penanda_blokir_benar_pada_rute_tanpa_pengguna_di_env(self):
        """Rute `auth='none'` (`/odoo`) tidak punya pengguna maupun perusahaan.

        Gerbang menerima pengguna dari pemanggilnya, dan perusahaannya harus
        ikut dari situ. Tanpa itu, penandanya ditulis ke perusahaan `False`,
        dan yang terlihat di log adalah "blocked for company False".
        """
        self.snapshot(status='expired')
        staf = self.env['res.users'].create({
            'name': 'Staf Tanpa Env',
            'login': 'staf.tanpa.env.presenly',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        guard = self.env['presenly.saas.guard'].with_user(None)

        self.assertEqual(
            guard.request_block_reason('/odoo', requester=staf), 'expired'
        )
        self.assertTrue(
            self.config.blocked_since,
            'penandanya tercatat di perusahaan pengguna, bukan di False',
        )

    def test_konfirmasi_baru_menghapus_penanda_blokir(self):
        self.snapshot(status='expired')
        self.guard.request_block_reason('/odoo')
        self.assertTrue(self.config.blocked_since)

        self.snapshot(status='active')
        self.assertFalse(self.config.blocked_since)

    # ------------------------------------------------------------------
    # Halaman blokir
    # ------------------------------------------------------------------
    def test_nilai_halaman_blokir_tanpa_rahasia(self):
        self.snapshot(status='expired', tenant_email='billing@contoh.test')
        values = self.guard.blocked_page_values()

        self.assertEqual(values['reason'], 'expired')
        self.assertEqual(values['company_name'], self.company.display_name)
        self.assertEqual(values['contact_email'], 'billing@contoh.test')
        self.assertTrue(values['is_manager'])

        terlihat = ' '.join(str(value) for value in values.values())
        self.assertNotIn('secret-key', terlihat, 'kunci API tidak boleh ikut')

    def test_pesan_galat_dan_kabar_ikut_dirender(self):
        self.snapshot(status='expired')
        values = self.guard.blocked_page_values(
            error='koneksi ditolak', message='masih belum aktif'
        )
        self.assertEqual(values['error'], 'koneksi ditolak')
        self.assertEqual(values['message'], 'masih belum aktif')


@tagged('post_install', '-at_install')
class TestPresenlyBlockedController(TransactionCase):
    """Pengendali halaman blokir: siapa yang boleh memakai tombolnya.

    Tidak diuji lewat HTTP karena token CSRF terikat pada sesi, dan staf yang
    diblokir tidak punya halaman berformulir untuk mengambilnya. Yang diuji di
    sini cabangnya; perutean dan halamannya diuji di `test_guard_http.py`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = PresenlySaasBlocked()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)
        cls.Subscription = cls.env['presenly.saas.subscription']
        cls.staf = cls.env['res.users'].create({
            'name': 'Staf Uji',
            'login': 'staf.uji.blocked',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True,
            'base_url': 'https://saas.example.com',
            'tenant_code': 'demo',
            'api_key': 'secret-key',
            'block_mode': 'enforce',
            'block_override_until': False,
            'blocked_since': False,
        })
        self.Subscription.search([]).unlink()
        self.Subscription._sync_from_payload(self.config, {
            'status': 'expired',
            'tenant_code': 'demo',
            'client_name': 'Tenant Uji',
        })

    def _call(self, method, as_user, **kwargs):
        """Panggil isi pengendalinya dengan `request` palsu, bukan server.

        Yang dipanggil method biasa (`_page`, `_refresh`, `_repair`), bukan
        rute-nya: `@http.route` membungkus rutenya dan mengubah nilai kembalian
        menjadi Response, sehingga cabangnya tidak lagi terbaca.

        Parameternya bernama `as_user`, bukan `user`: `odoo.tools.translate`
        menebak bahasa dari variabel lokal bernama `user` di tumpukan pemanggil,
        dan sebuah recordset di situ membuatnya gagal menghitung terjemahan.
        """
        env = self.env(user=as_user)
        fake = mock.Mock()
        fake.env = env
        fake.render.return_value = 'RENDERED'
        fake.redirect.return_value = 'REDIRECTED'
        # `_()` menebak bahasa pengguna dari permintaan yang sedang berjalan,
        # dan di tes unit tidak ada permintaan. Terjemahannya diuji di
        # `test_i18n_file.py`; di sini yang diuji cabangnya.
        terjemah = lambda pesan, *a, **k: pesan  # noqa: E731
        with mock.patch(
            'odoo.addons.presenly_saas.controllers.blocked.request', fake
        ), mock.patch(
            'odoo.addons.presenly_saas.controllers.blocked._', terjemah
        ), mock.patch(
            'odoo.addons.presenly_saas.models.presenly_saas_guard._', terjemah
        ):
            hasil = getattr(self.controller, method)(**kwargs)
        return hasil, fake

    def test_staf_tidak_bisa_menyegarkan(self):
        hasil, fake = self._call('_refresh', as_user=self.staf)
        self.assertEqual(hasil, 'RENDERED')
        self.assertIn(
            'Only a Presenly SaaS manager can refresh',
            fake.render.call_args[0][1]['error'],
        )

    def test_staf_tidak_bisa_memperbaiki_koneksi(self):
        _hasil, fake = self._call(
            '_repair', as_user=self.staf, base_url='http://127.0.0.1:1'
        )
        self.assertIn(
            'Only a Presenly SaaS manager can change',
            fake.render.call_args[0][1]['error'],
        )
        self.assertEqual(
            self.config.base_url, 'https://saas.example.com',
            'yang ditolak tidak boleh ikut menulis',
        )

    def test_halaman_menutup_diri_saat_tidak_diblokir(self):
        """Halaman blokir bukan pintu belakang saat langganannya sehat."""
        self.config.block_mode = 'off'
        hasil, _fake = self._call('_page', as_user=self.staf)
        self.assertEqual(hasil, 'REDIRECTED')
