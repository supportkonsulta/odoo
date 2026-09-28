"""Gerbang langganan terhadap server yang benar-benar berjalan.

`url_open` melewati tumpukan permintaan yang sama dengan pengguna sungguhan:
perutean, autentikasi, `ir.http._pre_dispatch`, lalu controller. Jadi yang
diuji di sini bukan logikanya (itu di `test_guard_gate.py`), melainkan bahwa
gerbangnya benar-benar terpasang: permintaan ditolak, halaman blokir tersaji,
dan yang harus tetap hidup tetap hidup.

Catatan lingkungan: di repo ini tabel rute Odoo dibangun sebelum modul dimuat,
sehingga sebagian rute bawaan modul bisa berakhir 404 di lingkungan tes. Yang
diuji di sini adalah rute bawaan Odoo (`/odoo`, `/web/login`, `/web/dataset/call_kw`)
dan satu rute milik modul ini; kalau yang terakhir tidak ditemukan, itu dicatat
di docstring kelasnya, bukan disembunyikan.
"""

from datetime import timedelta
import re

from odoo import fields
from odoo.tests import HttpCase, tagged

MANAGER_GROUP = 'presenly_saas.group_presenly_saas_manager'


@tagged('post_install', '-at_install')
class TestPresenlyGateHttp(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)
        cls.Subscription = cls.env['presenly.saas.subscription']

        cls.staf = cls.env['res.users'].create({
            'name': 'Staf HTTP',
            'login': 'staf.http.presenly',
            'password': 'staf-uji-123',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.manajer = cls.env['res.users'].create({
            'name': 'Manajer HTTP',
            'login': 'manajer.http.presenly',
            'password': 'manajer-uji-123',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref(MANAGER_GROUP).id,
            ])],
        })

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True,
            'base_url': 'https://saas.example.com',
            'tenant_code': 'demo',
            'api_key': 'secret-key',
            'block_mode': 'off',
            'block_override_until': False,
            'blocked_since': False,
        })
        self.Subscription.search([]).unlink()

    def snapshot(self, status):
        self.Subscription._sync_from_payload(self.config, {
            'status': status,
            'tenant_code': 'demo',
            'client_name': 'Tenant Uji',
            'current_period_end': fields.Datetime.now() + timedelta(days=30),
        })

    def block(self):
        self.config.block_mode = 'enforce'
        self.snapshot('expired')

    # ------------------------------------------------------------------
    # Tidak diblokir: perilaku lama tidak berubah
    # ------------------------------------------------------------------
    def test_backend_terbuka_saat_tidak_diblokir(self):
        self.authenticate('staf.http.presenly', 'staf-uji-123')
        self.assertEqual(self.url_open('/odoo').status_code, 200)

    def test_mode_uji_coba_tidak_menutup_backend(self):
        self.config.block_mode = 'dry_run'
        self.snapshot('expired')
        self.authenticate('staf.http.presenly', 'staf-uji-123')
        self.assertEqual(self.url_open('/odoo').status_code, 200)

    # ------------------------------------------------------------------
    # Diblokir
    # ------------------------------------------------------------------
    def test_backend_dialihkan_ke_halaman_blokir(self):
        self.block()
        self.authenticate('staf.http.presenly', 'staf-uji-123')

        response = self.url_open('/odoo', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn('/presenly_saas/blocked', response.headers.get('Location', ''))

        halaman = self.url_open('/odoo')
        self.assertEqual(halaman.status_code, 200)
        self.assertIn('Odoo is paused', halaman.text)
        self.assertIn('Expired', halaman.text)

    def test_panggilan_data_dijawab_galat_bukan_halaman(self):
        """Klien JSON-RPC mendapat galat yang bisa dibaca, bukan HTML."""
        self.block()
        self.authenticate('staf.http.presenly', 'staf-uji-123')

        response = self.url_open('/web/dataset/call_kw', json={
            'jsonrpc': '2.0',
            'method': 'call',
            'params': {'model': 'res.partner', 'method': 'search_read', 'args': [[]]},
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('paused', response.text)
        self.assertNotIn('<html', response.text.lower())

    def test_laporan_ikut_ditutup(self):
        self.block()
        self.authenticate('staf.http.presenly', 'staf-uji-123')
        response = self.url_open('/report/html/web.preview_external_layout', allow_redirects=False)
        self.assertEqual(response.status_code, 303)

    # ------------------------------------------------------------------
    # Yang tetap hidup
    # ------------------------------------------------------------------
    def test_halaman_masuk_dan_aset_tetap_hidup(self):
        self.block()
        halaman = self.url_open('/web/login')
        self.assertEqual(halaman.status_code, 200)

        # Aset yang diminta halaman blokir, lewat jalur yang sama dengan browser.
        aset = self.url_open('/web/assets/1/2/web.assets_web.min.js', allow_redirects=False)
        self.assertIn(aset.status_code, (200, 404))

    def test_halaman_blokir_menjelaskan_dan_membuka_jalan(self):
        self.block()

        # Staf: penjelasan, tanpa kontrol yang tidak bisa dipakainya.
        self.authenticate('staf.http.presenly', 'staf-uji-123')
        staf = self.url_open('/presenly_saas/blocked')
        self.assertEqual(staf.status_code, 200)
        self.assertIn('Ask your Presenly administrator', staf.text)
        self.assertNotIn('Refresh subscription', staf.text)

        # Manajer: tombol refresh dan formulir perbaikan koneksi.
        self.authenticate('manajer.http.presenly', 'manajer-uji-123')
        manajer = self.url_open('/presenly_saas/blocked')
        self.assertEqual(manajer.status_code, 200)
        self.assertIn('Refresh subscription', manajer.text)
        self.assertIn('Change the connection', manajer.text)

    def test_halaman_blokir_tidak_membocorkan_kunci_api(self):
        self.block()
        self.authenticate('manajer.http.presenly', 'manajer-uji-123')
        halaman = self.url_open('/presenly_saas/blocked')
        self.assertNotIn('secret-key', halaman.text)

    def test_backend_kembali_terbuka_setelah_akses_sementara(self):
        self.block()
        self.config.write({
            'block_override_until': fields.Datetime.now() + timedelta(days=1),
            'block_override_reason': 'perpanjangan sedang diproses',
        })
        self.authenticate('staf.http.presenly', 'staf-uji-123')
        self.assertEqual(self.url_open('/odoo').status_code, 200)

    def test_manajer_tidak_bisa_memakai_backend_saat_diblokir(self):
        """Halaman blokir untuk manajer, bukan backend untuk manajer."""
        self.block()
        self.authenticate('manajer.http.presenly', 'manajer-uji-123')
        self.assertEqual(
            self.url_open('/odoo', allow_redirects=False).status_code, 303
        )

    def test_sekoci_dari_config_parameter_membuka_backend(self):
        self.block()
        self.env['ir.config_parameter'].sudo().set_param(
            'presenly_saas_block_disabled', '1'
        )
        self.authenticate('staf.http.presenly', 'staf-uji-123')
        self.assertEqual(self.url_open('/odoo').status_code, 200)

    # ------------------------------------------------------------------
    # Jalan keluar: berhasil, ditolak, dan gagal
    # ------------------------------------------------------------------
    def _csrf_token(self, path='/presenly_saas/blocked'):
        """Token dari formulir yang benar-benar dirender halaman itu.

        Diambil dari halaman, bukan dikarang: token CSRF terikat pada sesi, dan
        mengambilnya dari formulir adalah cara browser memakainya. Kalau
        formulirnya lupa memuat token, tes ini yang mengetahuinya lebih dulu.
        """
        halaman = self.url_open(path)
        cocok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', halaman.text)
        self.assertTrue(cocok, 'formulir di %s tidak memuat token CSRF' % path)
        return cocok.group(1)

    def test_tanpa_token_csrf_permintaan_ditolak(self):
        """Lapisan pertama: dispatcher menolak permintaan tanpa token."""
        self.block()
        self.authenticate('staf.http.presenly', 'staf-uji-123')
        response = self.url_open('/presenly_saas/blocked/refresh', data={}, method='POST')
        self.assertEqual(response.status_code, 400)

    def test_tombol_segarkan_melaporkan_galat(self):
        """Lapisan kedua: dengan token sah, hasilnya tetap dilaporkan apa adanya."""
        self.block()
        self.config.base_url = 'http://127.0.0.1:1'
        self.authenticate('manajer.http.presenly', 'manajer-uji-123')

        response = self.url_open('/presenly_saas/blocked/refresh', data={
            'csrf_token': self._csrf_token(),
        }, method='POST')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Odoo is paused', response.text)
        self.assertIn('alert-warning', response.text, 'galatnya ditampilkan, bukan ditelan')

    def test_perbaikan_koneksi_menyimpan_dan_melaporkan_galat(self):
        """Keadaan gagal saat koneksi diperbaiki.

        Ini keadaan halaman blokir yang paling mudah terlupakan: kalau alamatnya
        salah, penyegaran gagal, dan pengguna harus melihat kenapa. Alamatnya
        diarahkan ke port yang tidak ada supaya gagalnya cepat dan tidak
        bergantung jaringan.
        """
        self.block()
        self.config.base_url = 'http://127.0.0.1:1'
        self.authenticate('manajer.http.presenly', 'manajer-uji-123')

        response = self.url_open('/presenly_saas/blocked/repair', data={
            'csrf_token': self._csrf_token(),
            'base_url': 'http://127.0.0.1:1',
            'tenant_code': 'demo',
            'api_key': '',
        }, method='POST')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Odoo is paused', response.text)
        self.assertIn('alert-warning', response.text)
        self.assertEqual(
            self.config.api_key, 'secret-key',
            'kolom kunci yang kosong berarti jangan ubah, bukan hapus',
        )
