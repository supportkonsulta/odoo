from unittest import mock

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPresenlyWeeklySchedule(TransactionCase):
    """Pola mingguan: lokasi kerja dan shift per hari.

    Yang dijaga tes ini adalah penghapusan berskop: baris yang hilang dari respons
    memang harus hilang, tetapi hanya milik pegawai yang muncul di respons itu.
    Kalau tarikannya terpotong, pegawai yang tidak terlihat tidak boleh ikut
    kehilangan jadwalnya.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Schedule = cls.env['presenly.saas.employee.schedule']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)

    def _baris(self, external_id, nopeg, hari, lokasi='Lokasi Uji', kerja=True):
        return {
            'id': external_id,
            'day_of_week': hari,
            'is_workday': kerja,
            'location': {'id': 500, 'name': lokasi},
            'shift': {'id': 9, 'name': 'Normal 1'},
            'employee': {'id': 1, 'nopeg': nopeg, 'name': nopeg},
            'priority': 0,
            'status': 'active',
            'valid_from': None,
            'valid_until': None,
        }

    def _tarik(self, baris):
        with mock.patch.object(type(self.config), '_client', lambda self: mock.Mock()), \
             mock.patch.object(type(self.config), '_fetch_pages', lambda *a, **k: (baris, {}, 1)):
            return self.config._pull_schedules()

    def test_jadwal_disimpan_dan_ditautkan_ke_pegawai(self):
        hr = self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-jadwal'})

        ringkas, error = self._tarik([
            self._baris(1, 'uji-jadwal', 'mon'),
            self._baris(2, 'uji-jadwal', 'tue', kerja=False),
        ])

        self.assertFalse(error)
        self.assertEqual(ringkas['created'], 2)
        senin = self.Schedule.search([
            ('employee_nopeg', '=', 'uji-jadwal'), ('day_of_week', '=', 'mon'),
        ])
        self.assertEqual(senin.location_name, 'Lokasi Uji')
        self.assertEqual(senin.shift_name, 'Normal 1')
        self.assertEqual(senin.hr_employee_id, hr)
        self.assertIn('Lokasi Uji', senin.name)

    def test_baris_yang_hilang_dihapus_untuk_pegawai_yang_terlihat(self):
        self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-jadwal'})
        self._tarik([self._baris(1, 'uji-jadwal', 'mon'), self._baris(2, 'uji-jadwal', 'tue')])

        # Respons berikutnya hanya memuat hari Senin.
        ringkas, _error = self._tarik([self._baris(1, 'uji-jadwal', 'mon')])

        self.assertEqual(ringkas['removed'], 1)
        self.assertEqual(
            self.Schedule.search([('employee_nopeg', '=', 'uji-jadwal')]).mapped('day_of_week'),
            ['mon'],
        )

    def test_pegawai_yang_tidak_terlihat_tidak_kehilangan_jadwalnya(self):
        """Tarikan yang terpotong tidak boleh menghapus jadwal orang lain."""
        self.Hr.create({'name': 'Satu', 'presenly_nopeg': 'uji-satu'})
        self.Hr.create({'name': 'Dua', 'presenly_nopeg': 'uji-dua'})
        self._tarik([self._baris(1, 'uji-satu', 'mon'), self._baris(2, 'uji-dua', 'mon')])

        ringkas, _error = self._tarik([self._baris(1, 'uji-satu', 'mon')])

        self.assertEqual(ringkas['removed'], 0)
        self.assertTrue(
            self.Schedule.search([('employee_nopeg', '=', 'uji-dua')]),
            'jadwal pegawai yang tidak muncul di respons dibiarkan',
        )

    def test_pegawai_yang_belum_ada_dihitung_bukan_dipaksakan(self):
        ringkas, error = self._tarik([self._baris(1, 'uji-belum-tersinkron', 'mon')])

        self.assertFalse(error)
        self.assertEqual(ringkas['without_employee'], 1)
        self.assertFalse(
            self.Schedule.search([('employee_nopeg', '=', 'uji-belum-tersinkron')]).hr_employee_id,
        )


@tagged('post_install', '-at_install')
class TestPresenlyWebhookBaseUrl(TransactionCase):
    """Alamat webhook diambil dari permintaan yang berjalan, bukan dari parameter.

    `web.base.url` bisa basi — pernah tertulis dari instance uji di port lain, dan
    alamat basi itu membuat webhook dikirim ke tempat yang tidak ada isinya tanpa
    galat yang terlihat.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.config.write({'enabled': True, 'active': True})

    def test_di_luar_permintaan_memakai_parameter(self):
        """Tanpa permintaan (mis. dari cron), parameter yang dipakai."""
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'http://contoh.test:8069')

        self.assertEqual(self.config._webhook_base_url(), 'http://contoh.test:8069')

    def test_alamat_diambil_dari_permintaan_yang_sedang_berjalan(self):
        """Ini yang membuat port yang berubah mendadak tetap benar.

        Parameter `web.base.url` bisa tertinggal dari instance atau port lain.
        Permintaan yang barusan dipakai operator menekan tombol adalah bukti
        paling jujur tentang alamat Odoo sekarang.
        """
        import odoo.http

        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'http://127.0.0.1:8079')
        request = mock.Mock()
        request.httprequest.host_url = 'http://localhost:8069/'

        with mock.patch.object(odoo.http, 'request', request):
            alamat = self.config._webhook_base_url()

        self.assertEqual(
            alamat, 'http://localhost:8069',
            'yang dipakai adalah alamat permintaan, bukan nilai parameter yang basi',
        )

    def test_uji_jangkau_melaporkan_kegagalan_apa_adanya(self):
        """Alamat yang tidak menjawab harus jadi pesan, bukan diam."""
        import requests

        self.config.webhook_secret = 'rahasia-uji'
        with mock.patch.object(requests, 'post', side_effect=OSError('connection refused')):
            berhasil, keterangan = self.config._webhook_self_check('http://tidak-ada:9/x')

        self.assertFalse(berhasil)
        self.assertIn('connection refused', keterangan)

    def test_uji_jangkau_menganggap_200_sebagai_berhasil(self):
        import requests

        self.config.webhook_secret = 'rahasia-uji'
        jawab = mock.Mock(status_code=200)
        with mock.patch.object(requests, 'post', return_value=jawab) as panggil:
            berhasil, keterangan = self.config._webhook_self_check('http://contoh.test:8069/x')

        self.assertTrue(berhasil)
        self.assertEqual(keterangan, 'HTTP 200')
        # Tanda tangannya harus ikut dikirim, kalau tidak ujinya tidak membuktikan apa pun.
        kiriman = panggil.call_args[1]
        self.assertIn('X-Presenly-Signature', kiriman['headers'])
        self.assertEqual(kiriman['headers']['X-Presenly-Event'], 'test.ping')


@tagged('post_install', '-at_install')
class TestPresenlySelfCheckTolerance(TransactionCase):
    """Uji-jangkau tidak boleh menjatuhkan pendaftarannya sendiri.

    Panggilan uji terjadi sebelum transaksi pendaftaran commit, jadi rahasia baru
    belum tersimpan dan tanda tangannya bisa ditolak walau semuanya benar. Yang
    penting dibedakan: 401 berarti alamatnya menjawab dan tokennya dikenal,
    sedangkan 404 berarti alamatnya menunjuk Odoo yang salah.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.config.write({'enabled': True, 'active': True, 'webhook_secret': 'rahasia-uji'})

    def _periksa(self, status):
        import requests

        with mock.patch.object(requests, 'post', return_value=mock.Mock(status_code=status)):
            return self.config._webhook_self_check('http://contoh.test:8069/x')

    def test_200_dianggap_berhasil(self):
        berhasil, keterangan = self._periksa(200)
        self.assertTrue(berhasil)
        self.assertEqual(keterangan, 'HTTP 200')

    def test_401_tetap_dianggap_menjawab(self):
        """Rahasia baru belum commit; tanda tangan ditolak, alamatnya tidak."""
        berhasil, keterangan = self._periksa(401)
        self.assertTrue(berhasil)
        self.assertEqual(keterangan, 'HTTP 401')

    def test_404_dianggap_gagal_karena_tokennya_tidak_dikenal(self):
        berhasil, keterangan = self._periksa(404)
        self.assertFalse(berhasil)
        self.assertEqual(keterangan, 'HTTP 404')

    def test_panggilan_uji_tidak_menulis_baris_konfigurasi(self):
        """Penulisan itu yang dulu membuat dua transaksi bentrok."""
        import inspect

        from odoo.addons.presenly_saas_hr.controllers import presenly_saas_webhook as modul

        sumber = inspect.getsource(modul.PresenlySaasWebhook.employee_webhook)
        cabang = sumber.split("event == 'test.ping'")[1].split('return')[0]
        self.assertNotIn(
            'write', cabang,
            'cabang test.ping tidak boleh menulis apa pun ke konfigurasi',
        )
