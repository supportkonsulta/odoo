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


@tagged('post_install', '-at_install')
class TestPresenlyWeeklySlots(TransactionCase):
    """Slot waktu: jam berapa sampai jam berapa, per hari.

    Payload slot hanya membawa id jadwal induknya, bukan hari, pegawai, atau
    lokasinya. Semuanya diambil dari baris jadwal yang sudah ada — dan kalau
    jadwalnya belum ada, dihitung, bukan ditebak.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Schedule = cls.env['presenly.saas.employee.schedule']
        cls.Slot = cls.env['presenly.saas.employee.slot']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)

    def _jadwal(self, external_id, nopeg, hari):
        jadwal = self.Schedule.create({
            'external_id': external_id, 'employee_nopeg': nopeg, 'name': nopeg,
            'day_of_week': hari, 'location_name': 'Lokasi Uji',
            'company_id': self.config.company_id.id,
        })
        pegawai = self.Hr.search([('presenly_nopeg', '=', nopeg)], limit=1)
        if pegawai:
            jadwal.hr_employee_id = pegawai.id
        return jadwal

    def _slot(self, external_id, jadwal_id, urutan=1):
        return {
            'id': external_id,
            'sequence': urutan,
            'start_time': '08:00:00',
            'end_time': '12:00:00',
            'status': 'active',
            'late_index': 5,
            'weekly_schedule': {'id': jadwal_id},
            'location': {'id': 5, 'name': 'Lokasi Uji'},
            'shift': {'id': 9, 'name': 'Normal 1'},
        }

    def _tarik(self, baris):
        with mock.patch.object(type(self.config), '_client', lambda self: mock.Mock()), \
             mock.patch.object(type(self.config), '_fetch_pages', lambda *a, **k: (baris, {}, 1)):
            return self.config._pull_slots()

    def test_slot_mengambil_hari_dan_pegawai_dari_jadwalnya(self):
        hr = self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-slot'})
        self._jadwal(501, 'uji-slot', 'mon')

        ringkas, error = self._tarik([self._slot(900, 501)])

        self.assertFalse(error)
        self.assertEqual(ringkas['created'], 1)
        slot = self.Slot.search([('external_id', '=', 900)])
        self.assertEqual(slot.day_of_week, 'mon')
        self.assertEqual(slot.employee_nopeg, 'uji-slot')
        self.assertEqual(slot.hr_employee_id, hr)
        self.assertEqual(slot.start_time, '08:00:00')
        self.assertIn('08:00:00', slot.name)

    def test_slot_tanpa_jadwal_dihitung_bukan_ditebak(self):
        ringkas, error = self._tarik([self._slot(901, 999)])

        self.assertFalse(error)
        self.assertEqual(ringkas['without_schedule'], 1)
        self.assertFalse(self.Slot.search([('external_id', '=', 901)]).day_of_week)

    def test_slot_yang_hilang_dihapus_hanya_untuk_jadwal_yang_terlihat(self):
        # Dua slot pada jadwal yang sama, dan satu slot pada jadwal lain.
        self._jadwal(502, 'uji-satu', 'mon')
        self._jadwal(503, 'uji-dua', 'tue')
        self._tarik([self._slot(902, 502, urutan=1), self._slot(903, 502, urutan=2),
                     self._slot(904, 503, urutan=1)])

        # Respons berikutnya hanya memuat slot pertama dari jadwal 502.
        ringkas, _error = self._tarik([self._slot(902, 502, urutan=1)])

        self.assertEqual(ringkas['removed'], 1, 'slot kedua jadwal 502 hilang')
        self.assertTrue(self.Slot.search([('external_id', '=', 902)]))
        self.assertFalse(self.Slot.search([('external_id', '=', 903)]))
        self.assertTrue(
            self.Slot.search([('external_id', '=', 904)]),
            'jadwal yang tidak muncul di respons tidak kehilangan slotnya',
        )


@tagged('post_install', '-at_install')
class TestPresenlySlotFillsDay(TransactionCase):
    """Satu hari boleh dipecah beberapa slot dengan lokasi dan shift berbeda.

    Kalau begitu, jadwal hariannya sendiri tidak membawa lokasi maupun shift —
    keduanya ada di slotnya. Barisnya diisi dari slot pertama supaya daftar
    hariannya tidak tampil kosong, tanpa menimpa isi yang sudah dikirim server.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Schedule = cls.env['presenly.saas.employee.schedule']
        cls.Slot = cls.env['presenly.saas.employee.slot']

    def _jadwal(self, external_id, nopeg, hari, lokasi=False, shift=False):
        return self.Schedule.create({
            'external_id': external_id, 'employee_nopeg': nopeg, 'name': nopeg,
            'day_of_week': hari, 'company_id': self.config.company_id.id,
            'location_name': lokasi or False, 'shift_name': shift or False,
        })

    def _slot(self, external_id, jadwal_id, urutan, lokasi, shift, mulai, selesai):
        return {
            'id': external_id, 'sequence': urutan,
            'start_time': mulai, 'end_time': selesai, 'status': 'active',
            'weekly_schedule': {'id': jadwal_id},
            'location': {'id': 5, 'name': lokasi},
            'shift': {'id': 9, 'name': shift},
        }

    def _tarik(self, baris):
        with mock.patch.object(type(self.config), '_client', lambda self: mock.Mock()), \
             mock.patch.object(type(self.config), '_fetch_pages', lambda *a, **k: (baris, {}, 1)):
            return self.config._pull_slots()

    def test_hari_tanpa_lokasi_mengambil_dari_slot_pertamanya(self):
        jadwal = self._jadwal(601, 'uji-slot-hari', 'mon')

        self._tarik([self._slot(910, 601, 1, 'Lokasi Pagi', 'Pagi', '07:00:00', '12:00:00')])

        self.assertEqual(jadwal.location_name, 'Lokasi Pagi')
        self.assertEqual(jadwal.shift_name, 'Pagi')
        self.assertEqual(jadwal.slot_summary, '07:00:00–12:00:00')

    def test_dua_slot_sehari_tercatat_keduanya(self):
        jadwal = self._jadwal(602, 'uji-dua-slot', 'tue')

        self._tarik([
            self._slot(911, 602, 1, 'Lokasi Pagi', 'Pagi', '07:00:00', '12:00:00'),
            self._slot(912, 602, 2, 'Lokasi Sore', 'Sore', '13:00:00', '17:00:00'),
        ])

        self.assertEqual(jadwal.slot_ids.mapped('location_name'),
                         ['Lokasi Pagi', 'Lokasi Sore'])
        self.assertIn('13:00:00–17:00:00', jadwal.slot_summary)

    def test_isi_yang_sudah_ada_tidak_ditimpa(self):
        jadwal = self._jadwal(603, 'uji-tidak-timpa', 'wed', lokasi='Lokasi Sendiri')

        self._tarik([self._slot(913, 603, 1, 'Lokasi Slot', 'Pagi', '07:00:00', '12:00:00')])

        self.assertEqual(jadwal.location_name, 'Lokasi Sendiri', 'isi server tidak ditimpa')
        self.assertEqual(jadwal.shift_name, 'Pagi', 'yang kosong tetap diisi')


@tagged('post_install', '-at_install')
class TestPresenlyUsualLocation(TransactionCase):
    """Lokasi kerja biasa diisi dari pola kerja, kalau penempatan tidak memberi.

    Penempatan tetap yang utama. Yang diisi hanya yang kosong — dan itu keadaan
    nyata: pegawai yang belum ditempatkan tetap punya pola kerja.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Schedule = cls.env['presenly.saas.employee.schedule']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)
        cls._urut = 0
        # Sakelarnya mati secara bawaan; tes ini menguji perilaku saat dinyalakan.
        cls.config.write({'fill_usual_location': True})

    def _lokasi(self, external_id, nama):
        alamat = self.env['res.partner'].create({'name': nama})
        return self.env['hr.work.location'].create({
            'name': nama, 'address_id': alamat.id,
            'company_id': self.config.company_id.id,
            'presenly_external_id': external_id,
        })

    def _hari(self, nopeg, hari, location_id, kerja=True, status='active'):
        self._urut += 1
        return self.Schedule.create({
            'external_id': 7000 + self._urut, 'employee_nopeg': nopeg, 'name': nopeg,
            'day_of_week': hari, 'is_workday': kerja, 'status': status,
            'location_id': location_id, 'location_name': 'Lokasi %s' % location_id,
            'company_id': self.config.company_id.id,
        })

    def test_terisi_dari_pola_kerja(self):
        hr = self.Hr.create({'name': 'Belum Ditempatkan', 'presenly_nopeg': 'uji-biasa'})
        lokasi = self._lokasi(801, 'Lokasi Pola')
        self._hari('uji-biasa', 'mon', 801)
        self._hari('uji-biasa', 'tue', 801)

        self.config._fill_usual_locations()

        self.assertEqual(hr.work_location_id, lokasi)

    def test_lokasi_yang_sudah_ada_tidak_ditimpa(self):
        punya = self._lokasi(802, 'Lokasi Penempatan')
        hr = self.Hr.create({
            'name': 'Sudah Ditempatkan', 'presenly_nopeg': 'uji-punya',
            'work_location_id': punya.id,
        })
        self._hari('uji-punya', 'mon', 803)

        self.config._fill_usual_locations()

        self.assertEqual(hr.work_location_id, punya, 'penempatan tetap yang utama')

    def test_yang_paling_sering_dipakai(self):
        hr = self.Hr.create({'name': 'Pola Campur', 'presenly_nopeg': 'uji-campur'})
        sering = self._lokasi(804, 'Lokasi Sering')
        self._lokasi(805, 'Lokasi Jarang')
        self._hari('uji-campur', 'mon', 804)
        self._hari('uji-campur', 'tue', 804)
        self._hari('uji-campur', 'wed', 805)

        self.config._fill_usual_locations()

        self.assertEqual(hr.work_location_id, sering)

    def test_hari_libur_dan_pola_lama_tidak_dihitung(self):
        hr = self.Hr.create({'name': 'Hanya Libur', 'presenly_nopeg': 'uji-libur'})
        self._lokasi(806, 'Lokasi Tidak Dipakai')
        self._hari('uji-libur', 'mon', 806, kerja=False)
        self._hari('uji-libur', 'tue', 806, status='inactive')

        ringkas = self.config._fill_usual_locations()

        self.assertFalse(hr.work_location_id)
        self.assertEqual(ringkas['no_schedule'], 1, 'tidak ada hari kerja yang berlaku')


@tagged('post_install', '-at_install')
class TestPresenlyScheduleHistoryDropped(TransactionCase):
    """Pola lama tidak disimpan.

    Aplikasi menyimpan riwayatnya: setiap perubahan meninggalkan baris `inactive`.
    Di Odoo riwayat itu hanya membuat daftarnya terlihat seperti duplikat — tujuh
    hari menjadi puluhan baris. Karena tarikannya punya aturan hapus berskop,
    menyaring di sini sekaligus membersihkan baris lama yang sudah tersimpan.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Schedule = cls.env['presenly.saas.employee.schedule']

    def _baris(self, external_id, hari, status='active'):
        return {
            'id': external_id, 'day_of_week': hari, 'is_workday': True,
            'status': status, 'location': {'id': 5, 'name': 'Lokasi Uji'},
            'shift': {'id': 9, 'name': 'Pagi'},
            'employee': {'id': 1, 'nopeg': 'uji-riwayat', 'name': 'Uji'},
            'valid_from': None, 'valid_until': None,
        }

    def _tarik(self, baris):
        with mock.patch.object(type(self.config), '_client', lambda self: mock.Mock()), \
             mock.patch.object(type(self.config), '_fetch_pages', lambda *a, **k: (baris, {}, 1)):
            return self.config._pull_schedules()

    def test_pola_lama_tidak_disimpan(self):
        ringkas, error = self._tarik([
            self._baris(1001, 'mon', 'active'),
            self._baris(1002, 'mon', 'inactive'),
        ])

        self.assertFalse(error)
        self.assertEqual(ringkas['created'], 1)
        self.assertEqual(ringkas['skipped'], 1)
        self.assertEqual(
            self.Schedule.search([('employee_nopeg', '=', 'uji-riwayat')]).mapped('day_of_week'),
            ['mon'], 'satu hari, satu baris',
        )

    def test_baris_lama_yang_sudah_tersimpan_ikut_terhapus(self):
        self._tarik([self._baris(1001, 'mon', 'active'), self._baris(1002, 'tue', 'active')])
        self.assertEqual(self.Schedule.search_count([('employee_nopeg', '=', 'uji-riwayat')]), 2)

        # Respons berikutnya tidak lagi memuat hari Selasa.
        ringkas, _error = self._tarik([self._baris(1001, 'mon', 'active')])

        self.assertEqual(ringkas['removed'], 1)
        self.assertEqual(
            self.Schedule.search([('employee_nopeg', '=', 'uji-riwayat')]).mapped('day_of_week'),
            ['mon'],
        )


class TestPresenlyUsualLocationOff(TestPresenlyUsualLocation):
    """Saat sakelarnya mati, tidak ada yang diisi.

    Lokasi kerja biasa milik penempatan; pola kerja hanya cadangan. Menyalakannya
    adalah keputusan, bukan efek samping.
    """

    def test_mati_secara_bawaan(self):
        self.config.fill_usual_location = False
        hr = self.Hr.create({'name': 'Sakelar Mati', 'presenly_nopeg': 'uji-mati'})
        self._lokasi(807, 'Lokasi Pola')
        self._hari('uji-mati', 'mon', 807)

        ringkas = self.config._fill_usual_locations()

        self.assertFalse(hr.work_location_id)
        self.assertTrue(ringkas.get('off'))


@tagged('post_install', '-at_install')
class TestPresenlyScheduleMode(TransactionCase):
    """Mode jadwal disimpulkan dari data, bukan disimpan.

    Pilihan yang disimpan bisa berbeda dari isinya, dan saat berbeda tidak ada
    yang tahu mana yang benar. Yang bisa dipercaya adalah datanya sendiri: ada
    slot atau tidak.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)
        cls.Slot = cls.env['presenly.saas.employee.slot']

    def _pegawai(self, nopeg):
        return self.Hr.create({'name': nopeg, 'presenly_nopeg': nopeg})

    def test_tanpa_slot_berarti_mode_mingguan(self):
        pegawai = self._pegawai('uji-mingguan')

        self.assertFalse(pegawai.presenly_uses_slots)

    def test_punya_slot_berarti_mode_slot(self):
        pegawai = self._pegawai('uji-slot-mode')
        self.Slot.create({
            'external_id': 8801, 'name': 'Slot', 'sequence': 1,
            'employee_nopeg': 'uji-slot-mode', 'day_of_week': 'mon',
            'hr_employee_id': pegawai.id, 'company_id': self.config.company_id.id,
        })

        self.assertTrue(pegawai.presenly_uses_slots)
