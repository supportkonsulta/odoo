from unittest import mock

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPresenlyPlacementConflict(TransactionCase):
    """Bentrok perusahaan dan lokasi kerja dari penempatan.

    Keduanya ditulis penarikan penempatan. Kalau seseorang mengubahnya di Odoo,
    nilai Presenly menang — tetapi tidak boleh menang tanpa catatan.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Mirror = cls.env['presenly.saas.employee']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)

    def _cermin(self, nopeg):
        return self.Mirror.create({
            'external_id': 7000 + len(nopeg),
            'nopeg': nopeg,
            'name': 'Pegawai Uji',
            'company_id': self.config.company_id.id,
        })

    def _penempatan(self, nopeg, perusahaan, lokasi):
        return [{
            'id': 1,
            'employee': {'id': 1, 'nopeg': nopeg, 'name': 'Pegawai Uji'},
            'internal_company': {'id': perusahaan.presenly_client_id, 'name': perusahaan.name},
            'location': {'id': lokasi.presenly_external_id, 'name': lokasi.name},
            'status': 'active',
            'is_primary': True,
            'valid_from': '2026-01-01',
        }]

    def test_perubahan_di_odoo_dilaporkan_saat_ditimpa(self):
        perusahaan = self.env['res.company'].create({
            'name': 'Klien Uji', 'presenly_client_id': 4242,
        })
        alamat = self.env['res.partner'].create({'name': 'Lokasi Uji'})
        lokasi = self.env['hr.work.location'].create({
            'name': 'Lokasi Uji', 'address_id': alamat.id, 'company_id': perusahaan.id,
            'presenly_external_id': 4243,
        })
        cermin = self._cermin('uji-bentrok')
        hr = self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-bentrok'})
        cermin.hr_employee_id = hr.id
        # Seolah nilainya pernah diterapkan, lalu diubah orang di Odoo.
        hr.presenly_synced_values = {
            'placement_client_id': perusahaan.presenly_client_id,
            'placement_work_location_id': lokasi.id,
        }
        # Seolah nilainya diubah orang di Odoo sesudah diterapkan — itulah yang
        # membuat penimpaan perlu dilaporkan.
        hr.presenly_client_id = 999
        hr.company_id = self.env.company

        # Kliennya ikut dipalsukan: argumen bawaan lambda penarikan dievaluasi
        # saat lambda dibuat, jadi `_client()` tetap dipanggil walaupun
        # `_fetch_pages` sudah diganti.
        baris = self._penempatan('uji-bentrok', perusahaan, lokasi)
        with mock.patch.object(type(self.config), '_client', lambda self: mock.Mock()), \
             mock.patch.object(type(self.config), '_fetch_pages', lambda *a, **k: (baris, {}, 1)):
            ringkas, error = self.config._pull_placements()

        self.assertFalse(error)
        self.assertEqual(
            ringkas['unknown_employee'], 0,
            'pegawainya harus ketemu; kalau tidak, ujiannya berhenti sebelum sampai',
        )
        self.assertEqual(len(ringkas['conflicts']), 1, 'bentroknya harus dilaporkan')
        self.assertEqual(
            hr.presenly_client_id, perusahaan.presenly_client_id,
            'nilai Presenly yang dipakai',
        )
        self.assertEqual(hr.company_id, self.config.company_id, 'perusahaan tetap milik integrasi')

    def test_snapshot_penempatan_tidak_dihapus_sinkronisasi_pegawai(self):
        """Kalau kuncinya hilang, pemeriksaan berikutnya kehilangan dasarnya."""
        self._cermin('uji-snapshot')
        hr = self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-snapshot'})
        hr.presenly_synced_values = {'placement_client_id': 99}
        cermin = self.Mirror.search([('nopeg', '=', 'uji-snapshot')], limit=1)

        snapshot = self.Mirror._snapshot_untuk(hr, cermin)

        self.assertEqual(
            snapshot.get('placement_client_id'), 99,
            'kunci milik penarikan lain tidak boleh terhapus',
        )
        self.assertIn('manager_nopeg', snapshot, 'kunci miliknya sendiri tetap ditulis')

    # ------------------------------------------------------------------
    # Penempatan yang sudah tidak ada lagi
    # ------------------------------------------------------------------
    def _lokasi(self, nama, external_id):
        alamat = self.env['res.partner'].create({'name': nama})
        return self.env['hr.work.location'].create({
            'name': nama, 'address_id': alamat.id,
            'company_id': self.config.company_id.id,
            'presenly_external_id': external_id,
        })

    def _tarik_tanpa_penempatan(self):
        """Penarikan yang tidak memuat penempatan siapa pun."""
        with mock.patch.object(type(self.config), '_client', lambda self: mock.Mock()), \
             mock.patch.object(type(self.config), '_fetch_pages',
                               lambda *a, **k: ([], {'total': 0}, 1)):
            return self.config._pull_placements()

    def test_penempatan_yang_hilang_mengembalikan_lokasi_kerja(self):
        """Lokasi kerja dikembalikan ketika penempatannya tidak ada lagi.

        Tanpa ini, pegawai tetap menunjuk lokasi dari penempatan yang sudah
        dihapus di Presenly — dan tidak ada tarikan mana pun yang memperbaikinya,
        karena penarikan hanya tahu penempatan yang **ada**.
        """
        lokasi = self._lokasi('Lokasi Bekas', 5151)
        self._cermin('uji-hilang')
        hr = self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-hilang'})
        hr.with_context(presenly_skip_push=True).write({
            'work_location_id': lokasi.id,
            'presenly_saas_config_id': self.config.id,
            'presenly_synced_values': {'placement_work_location_id': lokasi.id},
        })

        ringkas, error = self._tarik_tanpa_penempatan()

        self.assertFalse(error)
        self.assertFalse(hr.work_location_id, 'lokasi dari penempatan yang hilang dikosongkan')
        self.assertGreaterEqual(ringkas['cleared'], 1)

    def test_lokasi_yang_sudah_diubah_orang_tidak_dikosongkan(self):
        """Suntingan di Odoo dipertahankan, dan keadaannya dilaporkan.

        Mengosongkannya berarti menghapus pilihan orang tanpa jejak — persis yang
        dihindari di seluruh modul ini.
        """
        lokasi = self._lokasi('Lokasi Dipilih Orang', 5252)
        self._cermin('uji-diubah')
        hr = self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-diubah'})
        hr.with_context(presenly_skip_push=True).write({
            'work_location_id': lokasi.id,
            'presenly_saas_config_id': self.config.id,
            # Yang pernah dipasang penempatan adalah lokasi lain.
            'presenly_synced_values': {'placement_work_location_id': 999999},
        })

        ringkas, error = self._tarik_tanpa_penempatan()

        self.assertFalse(error)
        self.assertEqual(hr.work_location_id, lokasi, 'suntingan di Odoo dipertahankan')
        self.assertTrue(
            [c for c in ringkas['conflicts'] if 'uji-diubah' in c],
            'keadaannya harus dilaporkan, bukan didiamkan',
        )
