from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPresenlyConfigOwnership(TransactionCase):
    """Kepemilikan konfigurasi per record cermin.

    Record cermin boleh jadi milik perusahaan hasil cermin klien, sedangkan
    konfigurasi integrasinya dimiliki perusahaan pemasang. Di database dengan satu
    konfigurasi itu tidak jadi soal. Yang dijaga di sini adalah database dengan
    beberapa konfigurasi — dan basis datanya memang mengizinkannya, karena satu
    konfigurasi per perusahaan (constraint `presenly_saas_config_company_uniq`).
    Di sana kirim balik harus pergi ke tenant yang benar, dan kalau tidak ada dasar
    untuk memutuskan, ia ditolak — bukan ditebak.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        # Konfigurasi bawaan modul belum diaktifkan. Diaktifkan di sini karena
        # `_config_for_record()` memang menolak konfigurasi yang tidak aktif —
        # mengirim lewat integrasi yang dimatikan bukan hal yang diinginkan.
        cls.config.write({'enabled': True, 'active': True})
        cls.Lokasi = cls.env['hr.work.location'].with_context(active_test=False)

    def _config_kedua(self):
        """Konfigurasi aktif kedua, di perusahaan lain.

        Satu konfigurasi per perusahaan, jadi ambiguitas hanya mungkin muncul
        antar perusahaan — persis keadaan yang perlu ditangani.
        """
        perusahaan = self.env['res.company'].create({'name': 'Perusahaan Kedua'})
        return self.config.copy({'name': 'Koneksi Kedua', 'company_id': perusahaan.id})

    def _perusahaan_tanpa_konfigurasi(self):
        return self.env['res.company'].create({'name': 'Perusahaan Ketiga'})

    def _lokasi(self, company, config=None):
        alamat = self.env['res.partner'].create({'name': 'Lokasi Uji'})
        return self.Lokasi.create({
            'name': 'Lokasi Uji',
            'address_id': alamat.id,
            'company_id': company.id,
            'presenly_external_id': 77,
            'presenly_saas_config_id': config.id if config else False,
        })

    def test_pemilik_yang_tercatat_dipakai_apa_pun_keadaannya(self):
        """Yang pernah berhasil mengirim record itu yang berhak mengirim lagi."""
        lokasi = self._lokasi(self.config.company_id, config=self.config)
        self._config_kedua()

        self.assertEqual(
            self.config._config_for_record(lokasi), self.config,
            'pemilik yang tercatat harus menang atas pencarian yang ambigu',
        )

    def test_pemilik_dicatat_saat_pertama_kali_ditemukan(self):
        lokasi = self._lokasi(self.config.company_id)
        self.assertFalse(lokasi.presenly_saas_config_id)

        ditemukan = self.config._config_for_record(lokasi)

        self.assertEqual(ditemukan, self.config)
        self.assertEqual(
            lokasi.presenly_saas_config_id, self.config,
            'pemiliknya dicatat supaya pencarian berikutnya tidak ambigu lagi',
        )

    def test_ambigu_ditolak_bukan_ditebak(self):
        """Dua konfigurasi aktif, record tanpa pemilik: jangan pilih salah satu."""
        self._config_kedua()
        lokasi = self._lokasi(self._perusahaan_tanpa_konfigurasi())

        self.assertFalse(
            self.config._config_for_record(lokasi),
            'memilih salah satu berisiko mengirim data ke tenant Presenly yang salah',
        )
        self.assertFalse(lokasi.presenly_saas_config_id)

    def test_perusahaan_yang_punya_konfigurasi_sendiri_tidak_ambigu(self):
        """Kalau perusahaannya punya konfigurasi, itu yang dipakai — bukan tebakan."""
        perusahaan = self._perusahaan_tanpa_konfigurasi()
        kedua = self.env['presenly.saas.config'].create({
            'name': 'Koneksi Ketiga',
            'company_id': perusahaan.id,
            'enabled': True,
            'active': True,
        })
        lokasi = self._lokasi(perusahaan)

        self.assertEqual(kedua._config_for_record(lokasi), kedua)
