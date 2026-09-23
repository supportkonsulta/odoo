import hashlib
import hmac
import time

from odoo import _
from unittest import mock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..controllers.presenly_saas_webhook import SIGNATURE_TOLERANCE_SECONDS


@tagged('post_install', '-at_install')
class TestPresenlyWebhookVerification(TransactionCase):
    """Pemeriksaan panggilan webhook: yang sah diterima, yang tidak ditolak.

    Yang diuji di sini adalah logikanya, bukan jalur HTTP-nya. Jalur HTTP diuji
    terhadap server yang benar-benar berjalan; di lingkungan tes, tabel route
    Odoo dibangun sebelum modul ini dimuat, sehingga permintaan lewat
    `HttpCase` selalu berakhir 404 milik Odoo — bukan 404 milik penerima ini.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from ..controllers.presenly_saas_webhook import PresenlySaasWebhook
        cls.controller = PresenlySaasWebhook()
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.env.company)
        cls.config.sudo().write({
            'enabled': True,
            'webhook_enabled': True,
            'webhook_secret': 'rahasia-uji-penerima',
            'webhook_token': 'token-uji-penerima',
        })

    def _tanda_tangan(self, ts, body, secret=None):
        return 'sha256=' + hmac.new(
            (secret or self.config.webhook_secret).encode(),
            ('%s.%s' % (ts, body)).encode(),
            hashlib.sha256,
        ).hexdigest()

    def _sah(self, body, *, ts=None, secret=None, signature=None):
        ts = str(ts if ts is not None else int(time.time()))
        sig = signature if signature is not None else self._tanda_tangan(ts, body, secret)
        return self.controller._signature_is_valid(self.config, ts, body, sig)

    # ------------------------------------------------------------------
    # Tanda tangan
    # ------------------------------------------------------------------
    def test_tanda_tangan_sah_diterima(self):
        self.assertTrue(self._sah('{"a":1}'))

    def test_tanda_tangan_rahasia_lain_ditolak(self):
        self.assertFalse(self._sah('{"a":1}', secret='rahasia-yang-dikarang'))

    def test_badan_yang_diubah_ditolak(self):
        ts = str(int(time.time()))
        sig = self._tanda_tangan(ts, '{"a":1}')
        self.assertFalse(self._sah('{"a":2}', ts=ts, signature=sig))

    def test_cap_waktu_ikut_ditandatangani(self):
        ts = str(int(time.time()))
        sig = self._tanda_tangan(ts, '{"a":1}')
        # Cap waktu yang ditukar membuat tanda tangan lama tidak berlaku lagi.
        self.assertFalse(self._sah('{"a":1}', ts=int(ts) + 10, signature=sig))

    def test_tanpa_tanda_tangan_ditolak(self):
        self.assertFalse(self._sah('{"a":1}', signature=''))

    def test_prefiks_sha256_opsional_dibaca(self):
        ts = str(int(time.time()))
        telanjang = self._tanda_tangan(ts, '{"a":1}').replace('sha256=', '')
        self.assertTrue(self._sah('{"a":1}', ts=ts, signature=telanjang))

    # ------------------------------------------------------------------
    # Cap waktu
    # ------------------------------------------------------------------
    def test_cap_waktu_lama_ditolak(self):
        lama = int(time.time()) - SIGNATURE_TOLERANCE_SECONDS - 10
        self.assertFalse(self._sah('{"a":1}', ts=lama))

    def test_cap_waktu_terlalu_jauh_di_depan_ditolak(self):
        depan = int(time.time()) + SIGNATURE_TOLERANCE_SECONDS + 10
        self.assertFalse(self._sah('{"a":1}', ts=depan))

    def test_cap_waktu_bukan_angka_ditolak(self):
        self.assertFalse(self._sah('{"a":1}', ts='besok'))

    def test_rahasia_kosong_ditolak(self):
        self.config.sudo().write({'webhook_secret': False})
        try:
            # Tanda tangannya diberikan supaya pemeriksaan sampai ke soal
            # rahasianya, bukan berhenti karena tanda tangannya kosong.
            self.assertFalse(self._sah('{"a":1}', signature='sha256=apa-saja'))
        finally:
            self.config.sudo().write({'webhook_secret': 'rahasia-uji-penerima'})

    # ------------------------------------------------------------------
    # Pencarian token
    # ------------------------------------------------------------------
    def test_token_dikenal_ditemukan(self):
        hasil = self.env['presenly.saas.config']._find_by_webhook_token('token-uji-penerima')
        self.assertEqual(hasil, self.config)

    def test_token_asing_tidak_ditemukan(self):
        self.assertFalse(
            self.env['presenly.saas.config']._find_by_webhook_token('token-yang-dikarang')
        )

    def test_token_kosong_tidak_ditemukan(self):
        self.assertFalse(self.env['presenly.saas.config']._find_by_webhook_token(''))
        self.assertFalse(self.env['presenly.saas.config']._find_by_webhook_token(None))

    def test_webhook_nonaktif_tidak_ditemukan(self):
        self.config.sudo().write({'webhook_enabled': False})
        try:
            self.assertFalse(
                self.env['presenly.saas.config']._find_by_webhook_token('token-uji-penerima')
            )
        finally:
            self.config.sudo().write({'webhook_enabled': True})

    def test_koneksi_nonaktif_tidak_ditemukan(self):
        self.config.sudo().write({'enabled': False})
        try:
            self.assertFalse(
                self.env['presenly.saas.config']._find_by_webhook_token('token-uji-penerima')
            )
        finally:
            self.config.sudo().write({'enabled': True})

    # ------------------------------------------------------------------
    # Alamat penerima
    # ------------------------------------------------------------------
    def test_alamat_dibuat_dari_base_url_dan_token(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'web.base.url', 'https://odoo.example.com'
        )
        url = self.config._webhook_callback_url()
        self.assertTrue(url.startswith('https://odoo.example.com/presenly_saas/webhook/'))
        self.assertIn(self.config.webhook_token, url)

    def test_token_dibuat_bila_belum_ada(self):
        self.config.sudo().write({'webhook_token': False})
        self.config._webhook_callback_url()
        self.assertTrue(self.config.webhook_token)
        # Cukup panjang supaya tidak bisa ditebak.
        self.assertGreater(len(self.config.webhook_token), 20)

    def test_base_url_kosong_dilaporkan_bukan_dibiarkan(self):
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', '')
        hasil = self.config.action_register_webhook()
        self.assertEqual(hasil['params']['type'], 'danger')
        # Memakai `_()` polos, sama seperti modul. Di lingkungan tes `env.lang`
        # kosong, jadi `self.env._()` mengembalikan teks sumber dan tes ini akan
        # gagal di bahasa apa pun selain Inggris.
        self.assertIn(_('Webhook not registered'), hasil['params']['title'])


class TestPresenlyWebhookRouting(TestPresenlyWebhookVerification):
    """Peristiwa yang datang diarahkan ke penarikan yang sesuai.

    Sebelum ini setiap peristiwa menarik pegawai, apa pun namanya: perubahan
    klien memicu penarikan pegawai yang tidak ada hubungannya, dan perubahan
    lokasi kerja tidak pernah menyalin lokasinya ke `hr.work.location`.
    """

    def _sumber_untuk(self, event):
        Config = type(self.config)
        with mock.patch.object(Config, '_pull_employees', lambda self: ({'pulled': 0}, False)), \
             mock.patch.object(Config, '_pull_clients', lambda self: ({'created': 0}, False)), \
             mock.patch.object(Config, '_pull_reference_data', lambda self: ({'work_locations': {}}, False)):
            _ringkas, _error, sumber = self.controller._pull_for_event(self.config, event)
        return sumber

    def test_klien_menarik_klien(self):
        self.assertEqual(self._sumber_untuk('client.created'), 'clients')
        self.assertEqual(self._sumber_untuk('client.updated'), 'clients')

    def test_lokasi_kerja_menarik_cermin_acuan(self):
        self.assertEqual(self._sumber_untuk('work_location.created'), 'work_locations')
        self.assertEqual(self._sumber_untuk('work_location.updated'), 'work_locations')

    def test_pegawai_dan_peristiwa_tak_dikenal_menarik_pegawai(self):
        self.assertEqual(self._sumber_untuk('employee.updated'), 'employees')
        # Pengirim lama tidak menyertakan nama peristiwa; pegawai adalah tarikan
        # yang paling penting, jadi itu yang dijalankan.
        self.assertEqual(self._sumber_untuk(None), 'employees')
        self.assertEqual(self._sumber_untuk('sesuatu.yang.baru'), 'employees')
