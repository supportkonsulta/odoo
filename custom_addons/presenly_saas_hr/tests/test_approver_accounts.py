from unittest import mock

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPresenlyApproverAccounts(TransactionCase):
    """Daftar approver yang belum punya akun Odoo.

    Akunnya dibuat manual, tetapi mencari siapa yang perlu tidak perlu dikerjakan
    dari ingatan. Yang dijaga tes ini adalah batasnya: yang masuk daftar hanya
    mereka yang benar-benar ditunggu keputusannya atau punya bawahan, dan hanya
    yang belum punya akun.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)
        cls.Step = cls.env['presenly.saas.approval.step.leave']
        cls.Leave = cls.env['presenly.saas.leave']
        cls._urutan = 0

    def _pegawai(self, nopeg, nama, atasan=None, pengguna=False):
        pegawai = self.Hr.create({
            'name': nama,
            'presenly_nopeg': nopeg,
            'parent_id': atasan.id if atasan else False,
        })
        if pengguna:
            self._urutan += 1
            akun = self.env['res.users'].create({
                'name': nama,
                'login': 'akun-%s-%s' % (nopeg or 'x', self._urutan),
                'email': '%s@example.com' % (nopeg or 'x'),
            })
            pegawai.user_id = akun
        return pegawai

    def _pengajuan_menunggu(self, nopeg_ditunggu):
        self._urutan += 1
        pengajuan = self.Leave.create({
            'external_id': 8000 + self._urutan,
            'reference_number': 'UJI-%s' % self._urutan,
            'employee_nopeg': 'pemohon',
            'status': 'pending',
            'approval_current_level': 1,
            'approval_total_levels': 2,
        })
        self.Step.create({
            'leave_id': pengajuan.id, 'level': 1, 'approver_type': 'user',
            'expected_nopeg': nopeg_ditunggu, 'step_status': 'pending',
        })
        return pengajuan

    def test_yang_ditunggu_keputusannya_masuk_daftar(self):
        self._pegawai('uji-ditunggu', 'Feri')
        self._pengajuan_menunggu('uji-ditunggu')

        daftar = self.Hr._presenly_perlu_akun()

        self.assertIn('uji-ditunggu', daftar.mapped('presenly_nopeg'))

    def test_yang_sudah_punya_akun_tidak_masuk_daftar(self):
        self._pegawai('uji-ditunggu', 'Feri', pengguna=True)
        self._pengajuan_menunggu('uji-ditunggu')

        daftar = self.Hr._presenly_perlu_akun()

        self.assertNotIn('uji-ditunggu', daftar.mapped('presenly_nopeg'))

    def test_yang_punya_bawahan_masuk_daftar(self):
        """Level terakhir bertipe `direct_manager`, jadi atasan akan menerima."""
        atasan = self._pegawai('uji-atasan', 'Yusril')
        self._pegawai('uji-bawahan', 'Rangga', atasan=atasan)

        daftar = self.Hr._presenly_perlu_akun()

        self.assertIn('uji-atasan', daftar.mapped('presenly_nopeg'))
        self.assertNotIn(
            'uji-bawahan', daftar.mapped('presenly_nopeg'),
            'yang tidak ditunggu dan tidak punya bawahan tidak perlu akun',
        )

    def test_langkah_yang_sudah_diputuskan_tidak_membuat_orang_masuk_daftar(self):
        self._pegawai('uji-ditunggu', 'Feri')
        pengajuan = self._pengajuan_menunggu('uji-ditunggu')
        pengajuan.approval_step_ids.write({'acted_at': '2026-09-01 08:00:00'})

        daftar = self.Hr._presenly_perlu_akun()

        self.assertNotIn(
            'uji-ditunggu', daftar.mapped('presenly_nopeg'),
            'yang sudah diputuskan tidak lagi ditunggu',
        )


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
            'placement_company_id': perusahaan.id,
            'placement_work_location_id': lokasi.id,
        }
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
        self.assertEqual(hr.company_id, perusahaan, 'nilai Presenly yang dipakai')

    def test_snapshot_penempatan_tidak_dihapus_sinkronisasi_pegawai(self):
        """Kalau kuncinya hilang, pemeriksaan berikutnya kehilangan dasarnya."""
        self._cermin('uji-snapshot')
        hr = self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-snapshot'})
        hr.presenly_synced_values = {'placement_company_id': 99}
        cermin = self.Mirror.search([('nopeg', '=', 'uji-snapshot')], limit=1)

        snapshot = self.Mirror._snapshot_untuk(hr, cermin)

        self.assertEqual(
            snapshot.get('placement_company_id'), 99,
            'kunci milik penarikan lain tidak boleh terhapus',
        )
        self.assertIn('manager_nopeg', snapshot, 'kunci miliknya sendiri tetap ditulis')
