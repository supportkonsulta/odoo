from unittest import mock

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPresenlyReconciliation(TransactionCase):
    """Rekonsiliasi: membandingkan, melaporkan, dan tidak menebak.

    Yang diuji di sini adalah sifat yang membuat alat ini berguna, bukan sekadar
    jalan: temuan yang sama tidak boleh menumpuk tiap pemeriksaan, temuan yang
    bedanya hilang harus menutup sendiri, dan "berubah di kedua sisi" harus
    dibedakan dari "berbeda" — yang pertama itulah yang kehilangan suntingan
    tanpa jejak kalau tidak dilaporkan.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.config.write({'sync_work_locations': True})
        cls.Laporan = cls.env['presenly.saas.reconciliation']
        cls.CerminLokasi = cls.env['presenly.saas.work.location']
        cls.CerminPegawai = cls.env['presenly.saas.employee']
        cls.Lokasi = cls.env['hr.work.location'].with_context(active_test=False)
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)

    def _jalankan(self):
        """Jalankan pemeriksaan tanpa menyentuh jaringan.

        Perbandingan klien memanggil API, dan itu sengaja diganti: tes ini tentang
        pembandingnya, bukan tentang klien HTTP-nya.
        """
        ringkasan = {'checked': 0, 'open': 0, 'resolved': 0, 'by_dataset': {}}
        with mock.patch.object(
            type(self.config), '_reconcile_clients', lambda self, keys: 0
        ):
            self.config.reconcile()
        return ringkasan

    def _temuan(self, dataset, kunci, kolom):
        return self.Laporan.search([
            ('config_id', '=', self.config.id),
            ('dataset', '=', dataset),
            ('presenly_key', '=', kunci),
            ('field_name', '=', kolom),
        ], limit=1)

    def _pasangan_lokasi(self, radius_presenly=250, radius_odoo=250):
        cermin = self.CerminLokasi.create({
            'external_id': 99,
            'name': 'Lokasi Uji',
            'radius_meters': radius_presenly,
            'latitude': -7.1,
            'longitude': 112.6,
            'timezone': 'Asia/Jakarta',
            'attendance_type': 'normal',
            'is_active': True,
            'company_id': self.config.company_id.id,
        })
        # `address_id` wajib di `hr.work.location`, jadi alamatnya dibuat lebih
        # dulu — sama seperti yang dilakukan penarikan lokasi.
        alamat = self.env['res.partner'].create({
            'name': 'Lokasi Uji',
            'street': 'Jalan Uji 1',
        })
        native = self.Lokasi.create({
            'name': 'Lokasi Uji',
            'address_id': alamat.id,
            'presenly_external_id': 99,
            'presenly_radius_meters': radius_odoo,
            'presenly_latitude': -7.1,
            'presenly_longitude': 112.6,
            'presenly_timezone': 'Asia/Jakarta',
            'presenly_attendance_type': 'normal',
            'company_id': self.config.company_id.id,
        })
        return cermin, native

    # ------------------------------------------------------------------
    def test_lokasi_yang_berbeda_dilaporkan_dengan_kedua_nilainya(self):
        self._pasangan_lokasi(radius_presenly=250, radius_odoo=180)

        self.config.reconcile()

        baris = self._temuan('work_location', '99', 'radius_meters')
        self.assertTrue(baris, 'perbedaan radius seharusnya dilaporkan')
        self.assertEqual(baris.presenly_value, '250')
        self.assertEqual(baris.odoo_value, '180')
        self.assertEqual(baris.nature, 'differs')
        self.assertEqual(baris.state, 'open')
        # Tidak ada snapshot untuk lokasi, jadi tidak ada dasar mengaku tahu mana
        # yang berubah lebih dulu.
        self.assertNotEqual(baris.nature, 'both_changed')

    def test_kolom_yang_sama_tidak_dilaporkan(self):
        self._pasangan_lokasi(radius_presenly=250, radius_odoo=250)

        self.config.reconcile()

        self.assertFalse(
            self._temuan('work_location', '99', 'radius_meters'),
            'nilai yang sama bukan temuan',
        )

    def test_pemeriksaan_ulang_memperbarui_bukan_menumpuk(self):
        _cermin, native = self._pasangan_lokasi(radius_presenly=250, radius_odoo=180)

        self.config.reconcile()
        native.write({'presenly_radius_meters': 300})
        self.config.reconcile()

        semua = self.Laporan.search([
            ('dataset', '=', 'work_location'), ('presenly_key', '=', '99'),
            ('field_name', '=', 'radius_meters'),
        ])
        self.assertEqual(len(semua), 1, 'satu kolom, satu baris')
        self.assertEqual(semua.odoo_value, '300', 'nilainya diperbarui')

    def test_temuan_yang_bedanya_hilang_menutup_sendiri(self):
        _cermin, native = self._pasangan_lokasi(radius_presenly=250, radius_odoo=180)
        self.config.reconcile()
        self.assertEqual(self._temuan('work_location', '99', 'radius_meters').state, 'open')

        native.write({'presenly_radius_meters': 250})
        self.config.reconcile()

        baris = self._temuan('work_location', '99', 'radius_meters')
        self.assertEqual(baris.state, 'resolved')
        self.assertTrue(baris.resolved_at)

    def test_keputusan_manusia_tidak_dibatalkan_pemeriksaan_berikutnya(self):
        self._pasangan_lokasi(radius_presenly=250, radius_odoo=180)
        self.config.reconcile()

        baris = self._temuan('work_location', '99', 'radius_meters')
        baris.write({'state': 'ignored', 'note': 'Memang disengaja.'})
        self.config.reconcile()

        self.assertEqual(
            self._temuan('work_location', '99', 'radius_meters').state, 'ignored',
            'yang sudah diputuskan manusia tidak boleh dibuka lagi oleh mesin',
        )

    def test_pegawai_yang_berubah_di_kedua_sisi_ditandai(self):
        """Ini temuan yang paling penting: suntingan Odoo yang akan hilang."""
        cermin = self.CerminPegawai.create({
            'external_id': 501, 'nopeg': 'uji-1', 'name': 'Pegawai Uji',
            'company_id': self.config.company_id.id,
        })
        hr = self.Hr.create({
            'name': 'Pegawai Uji',
            'presenly_nopeg': 'uji-1',
            # Snapshot: nilai yang terakhir disepakati kedua sisi.
            'presenly_synced_values': {'name': 'Pegawai Uji'},
        })
        cermin.hr_employee_id = hr.id

        # Diubah di kedua sisi sejak sinkronisasi terakhir.
        cermin.write({'name': 'Nama dari Presenly'})
        hr.write({'name': 'Nama dari Odoo'})

        self.config.reconcile()

        baris = self._temuan('employee', 'uji-1', 'name')
        self.assertTrue(baris)
        self.assertEqual(baris.nature, 'both_changed')
        self.assertEqual(baris.presenly_value, 'Nama dari Presenly')
        self.assertEqual(baris.odoo_value, 'Nama dari Odoo')

    def test_satu_dataset_gagal_tidak_membisukan_yang_lain(self):
        """Perbandingan klien butuh API; lokasi tidak. Kegagalan jaringan pada
        yang pertama tidak boleh menyembunyikan temuan pada yang kedua."""
        self._pasangan_lokasi(radius_presenly=250, radius_odoo=180)

        # Kegagalannya dipaksa, bukan diharapkan dari keadaan lingkungan: tes
        # yang bergantung pada ada-tidaknya jaringan akan lulus di satu mesin dan
        # gagal di mesin lain tanpa ada kode yang berubah.
        with mock.patch.object(
            type(self.config), '_reconcile_clients',
            side_effect=OSError('jaringan putus'),
        ):
            ringkasan, error = self.config.reconcile()

        self.assertFalse(error)
        self.assertIn('client', ringkasan['errors'])
        self.assertTrue(
            self._temuan('work_location', '99', 'radius_meters'),
            'dataset yang gagal tidak boleh membatalkan pemeriksaan dataset lain',
        )

    def test_pegawai_tanpa_padanan_dilaporkan_hilang(self):
        self.CerminPegawai.create({
            'external_id': 502, 'nopeg': 'uji-2', 'name': 'Belum Tertaut',
            'company_id': self.config.company_id.id,
        })

        self.config.reconcile()

        baris = self._temuan('employee', 'uji-2', 'hr_employee_id')
        self.assertTrue(baris)
        self.assertEqual(baris.nature, 'missing_in_odoo')
