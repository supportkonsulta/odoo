"""Setiap pengguna melihat datanya sendiri.

Sampai versi sebelumnya pengguna internal melihat satu cabang penuh untuk
pengajuan, dan cermin presensi tidak punya aturan sama sekali. Berkas ini menjaga
lima hal:

1. pengguna biasa hanya melihat barisnya sendiri, pada presensi dan pengajuan;
2. baris rekan sekantor, walaupun satu cabang, tidak terlihat;
3. pengguna yang belum tertaut ke pegawai melihat nol baris, bukan semuanya;
4. Approver tetap melihat satu cabang, Manager tetap melihat perusahaannya;
5. nopeg pengguna terisi walaupun record pegawainya ada di perusahaan lain -
   `user.employee_id` tidak bisa dipakai untuk itu.
"""

from odoo.tests import TransactionCase, tagged


def overtime_row(external_id, nopeg):
    return {
        'id': external_id,
        'overtime_date': '2026-09-21',
        'purpose': 'Penutupan bulan',
        'start_time': '17:00:00',
        'end_time': '19:00:00',
        'total_hours': 2.0,
        'day_type': 'workday',
        'approval_status': 'approved',
        'employee': {'id': 2, 'nopeg': nopeg, 'name': nopeg},
        'location': {'id': 501, 'name': 'Lokasi Uji'},
    }


def attendance_row(external_id, nopeg):
    return {
        'id': external_id,
        'work_date': '2026-09-21',
        'user_id': 2,
        'status': 'closed',
        'employee': {'id': 2, 'nopeg': nopeg, 'name': nopeg},
        'location': {'id': 501, 'name': 'Lokasi Uji'},
    }


@tagged('post_install', '-at_install')
class TestPresenlyOwnDataRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Overtime = cls.env['presenly.saas.overtime']
        cls.Log = cls.env['presenly.saas.attendance.log']
        cls.Location = cls.env['presenly.saas.work.location']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)
        cls.Mirror = cls.env['presenly.saas.employee']
        cls.User = cls.env['res.users']
        # Penghitung id cermin pegawai: harus unik per perusahaan.
        cls._external_id = 8000

    def setUp(self):
        super().setUp()
        self.Overtime.search([]).unlink()
        self.Log.search([]).unlink()
        self.Location.search([]).unlink()
        self.Hr.search([('presenly_nopeg', 'like', 'uji-%')]).unlink()
        self.Mirror.search([('nopeg', 'like', 'uji-%')]).unlink()
        self.User.search([('login', 'like', 'uji.')]).unlink()

    # ------------------------------------------------------------------
    # Bantu
    # ------------------------------------------------------------------
    def _pegawai(self, nopeg, perusahaan=None, dengan_akun=None):
        """Cermin pegawai dan `hr.employee`-nya, sudah tertaut.

        Cerminnya dibuat karena tautan pada pengajuan dicocokkan lewat cermin
        (per nopeg), bukan langsung ke `hr.employee`: tanpa cermin, kolom
        `hr_employee_id` kosong dan aturan "milik sendiri" tidak menemukan apa pun
        karena sebab yang tidak ada hubungannya dengan aturan itu.
        """
        # Id cermin harus unik per perusahaan: `8000 + len(nopeg)` pernah
        # bertabrakan untuk dua nopeg yang panjangnya sama.
        type(self)._external_id += 1
        cermin = self.Mirror.create({
            'external_id': type(self)._external_id,
            'nopeg': nopeg,
            'name': 'Pegawai %s' % nopeg,
            'company_id': (perusahaan or self.company).id,
        })
        hr = self.Hr.create({
            'name': 'Pegawai %s' % nopeg,
            'presenly_nopeg': nopeg,
            'user_id': dengan_akun.id if dengan_akun else False,
            'company_id': (perusahaan or self.company).id,
        })
        cermin.hr_employee_id = hr.id
        return hr

    def _pengguna(self, login, groups=None, companies=None):
        return self.User.create({
            'name': login,
            'login': login,
            'company_id': self.company.id,
            'company_ids': [(6, 0, [c.id for c in (companies or [self.company])])],
            'group_ids': [(6, 0, [
                g.id for g in (groups or [self.env.ref('base.group_user')])
            ])],
        })

    def _lokasi(self, external_id, klien_id=1):
        return self.Location.create({
            'external_id': external_id,
            'name': 'Lokasi Uji',
            'company_id': self.company.id,
            'internal_company_id': klien_id,
            'internal_company_name': 'CLIENT %s' % klien_id,
        })

    def _dua_lembur(self):
        """Dua lembur, satu untuk setiap pegawai, di perusahaan yang sama."""
        self._lokasi(501)
        self.Overtime._mirror_replace(self.company, [
            overtime_row(9101, 'uji-a'),
            overtime_row(9102, 'uji-b'),
        ])

    def _dua_presensi(self):
        self.Log._upsert_rows(self.company, [
            attendance_row(7101, 'uji-a'),
            attendance_row(7102, 'uji-b'),
        ])

    def _tautkan_pegawai(self, pegawai, pengguna):
        pegawai.write({'user_id': pengguna.id})
        return self.User.browse(pengguna.id)

    # ------------------------------------------------------------------
    # Milik sendiri
    # ------------------------------------------------------------------
    def test_presensi_hanya_milik_sendiri(self):
        self._dua_presensi()
        pengguna = self._pengguna('uji.presensi.a')
        self._tautkan_pegawai(self._pegawai('uji-a'), pengguna)
        self._tautkan_pegawai(self._pegawai('uji-b'), self._pengguna('uji.presensi.b'))

        terlihat = self.Log.with_user(pengguna).search([]).mapped('external_id')

        self.assertEqual(terlihat, [7101], 'rekan sekerja tidak boleh terlihat')

    def test_pengajuan_hanya_milik_sendiri(self):
        # Pegawainya dibuat lebih dulu: kolom `hr_employee_id` diisi saat barisnya
        # ditulis, dengan mencocokkan nopeg ke cermin pegawai.
        pengguna = self._pengguna('uji.lembur.a')
        self._tautkan_pegawai(self._pegawai('uji-a'), pengguna)
        self._tautkan_pegawai(self._pegawai('uji-b'), self._pengguna('uji.lembur.b'))

        self._dua_lembur()

        terlihat = self.Overtime.with_user(pengguna).search([]).mapped('external_id')

        self.assertEqual(terlihat, [9101])

    def test_pengguna_tanpa_nopeg_tidak_melihat_apa_pun(self):
        self._dua_presensi()
        self._dua_lembur()
        pengguna = self._pengguna('uji.tanpa.nopeg')

        self.assertEqual(self.Log.with_user(pengguna).search_count([]), 0)
        self.assertEqual(self.Overtime.with_user(pengguna).search_count([]), 0)

    def test_nopeg_milik_pegawai_di_perusahaan_lain_tetap_terbaca(self):
        """`user.employee_id` hanya melihat perusahaan yang sedang aktif.

        Karena itu aturannya memakai kolom nopeg di pengguna. Kalau kolom itu
        kembali dihitung dari `employee_id`, tes ini gagal - dan kegagalannya di
        dunia nyata berupa pegawai cabang yang tidak bisa melihat datanya sendiri.
        """
        cabang = self.env['res.company'].create({
            'name': 'CLIENT Uji', 'presenly_client_id': 9099,
        })
        pengguna = self._pengguna('uji.perusahaan.lain', companies=[self.company])
        self._tautkan_pegawai(self._pegawai('uji-a', perusahaan=cabang), pengguna)

        self.assertEqual(
            pengguna.presenly_nopeg, 'uji-a',
            'nopeg harus terisi walaupun pegawainya bukan di perusahaan aktif',
        )

    def test_nopeg_untuk_keputusan_dibaca_walau_perusahaannya_bukan_perusahaan_aktif(self):
        """Penghalang "belum tertaut nopeg" tidak boleh muncul karena perusahaan.

        Tombol keputusan mengambil nopeg dari pengguna, dan dulu lewat
        `user.employee_id` - pegawai pada perusahaan yang **sedang aktif**. Di
        basis nyata pengguna cabang berperusahaan aktif perusahaan cabang,
        sedangkan record pegawainya di perusahaan integrasi, jadi nopegnya tidak
        terbaca dan keputusannya ditolak walaupun nopegnya terisi.
        """
        cabang = self.env['res.company'].create({
            'name': 'CLIENT Keputusan', 'presenly_client_id': 9098,
        })
        pengguna = self._pengguna('uji.keputusan.cabang')
        self._tautkan_pegawai(self._pegawai('uji-a'), pengguna)
        # Perusahaan aktifnya cabang, dan dia memang tidak punya perusahaan
        # integrasi - persis keadaan pengguna cabang di lapangan.
        pengguna.write({
            'company_id': cabang.id,
            'company_ids': [(6, 0, [cabang.id])],
        })
        self._dua_lembur()
        baris = self.Overtime.with_user(pengguna).search([('external_id', '=', 9101)])

        # `employee_id` dinilai pada perusahaan yang sedang aktif; dengan cabang
        # yang aktif, pegawai di perusahaan integrasi tidak terlihat.
        self.assertFalse(
            pengguna.with_company(cabang).employee_id,
            'prasyarat tes: employee_id memang kosong di keadaan ini',
        )
        self.assertEqual(
            baris.with_company(cabang)._presenly_actor_nopeg(), 'uji-a',
            'nopeg pembuat keputusan harus terbaca',
        )

    def test_nopeg_mengikuti_perubahan_pegawai(self):
        pengguna = self._pengguna('uji.ganti.nopeg')
        pegawai = self._tautkan_pegawai(self._pegawai('uji-a'), pengguna)
        self.assertEqual(pengguna.presenly_nopeg, 'uji-a')

        pegawai.presenly_nopeg = 'uji-c'

        self.assertEqual(pengguna.presenly_nopeg, 'uji-c')

    # ------------------------------------------------------------------
    # Yang tidak boleh kehilangan pandangan
    # ------------------------------------------------------------------
    def test_approver_melihat_satu_cabang(self):
        # Perusahaan cabangnya dibuat lebih dulu: cabang diturunkan dari lokasi
        # saat barisnya ditulis, jadi tanpa itu kolomnya kosong.
        cabang = self.env['res.company'].create({
            'name': 'CLIENT 1', 'presenly_client_id': 1,
        })
        self._dua_lembur()
        self._dua_presensi()
        approver = self._pengguna(
            'uji.approver',
            groups=[self.env.ref('base.group_user'),
                    self.env.ref('presenly_saas_hr.group_presenly_saas_approver')],
            companies=[self.company, cabang],
        )

        self.assertEqual(
            self.Overtime.with_user(approver).search_count([]), 2,
            'approver memutuskan pengajuan, jadi ia harus melihat cabangnya',
        )
        self.assertEqual(
            self.Log.with_user(approver).search_count([]), 2,
            'approver melihat presensi pada perusahaan yang ia izinkan',
        )

    def test_pengelola_tidak_kehilangan_pandangan(self):
        self._dua_lembur()
        self._dua_presensi()
        pengelola = self._pengguna(
            'uji.pengelola.own',
            groups=[self.env.ref('base.group_user'),
                    self.env.ref('presenly_saas.group_presenly_saas_manager')],
        )

        self.assertEqual(self.Overtime.with_user(pengelola).search_count([]), 2)
        self.assertEqual(self.Log.with_user(pengelola).search_count([]), 2)

    def test_hr_tidak_kehilangan_pandangan(self):
        grup_hr = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
        if not grup_hr:
            self.skipTest('hr tidak terpasang di basis data ini')
        self._dua_lembur()
        self._dua_presensi()
        hr = self._pengguna('uji.hr.own', groups=[grup_hr])

        self.assertEqual(self.Overtime.with_user(hr).search_count([]), 2)
        self.assertEqual(self.Log.with_user(hr).search_count([]), 2)

    def test_baris_milik_sendiri_terlihat_walau_perusahaannya_bukan_miliknya(self):
        """Kenyataan di lapangan, dan alasan aturan ini tidak berpagar perusahaan.

        Di basis nyata `yusril` hanya punya CLIENT 1 dan CLIENT 2, sedangkan
        seluruh baris cermin berada di perusahaan integrasi. Kalau aturan "milik
        sendiri" diberi pagar `company_id in company_ids`, pegawai cabang justru
        kehilangan datanya sendiri.

        Yang dijaga tes ini: baris milik sendiri tetap terlihat. Kalau nanti ada
        yang menambahkan pagar itu, tes ini gagal sebelum penggunanya mengeluh.
        """
        self._dua_presensi()
        perusahaan_lain = self.env['res.company'].create({'name': 'Tenant Lain'})
        self.Log.sudo().create({
            'external_id': 7199, 'work_date': '2026-09-21',
            'employee_nopeg': 'uji-b', 'company_id': perusahaan_lain.id,
        })
        pengguna = self._pengguna('uji.tenant.lain')
        self._tautkan_pegawai(self._pegawai('uji-a'), pengguna)

        terlihat = self.Log.with_user(pengguna).search([]).mapped('employee_nopeg')

        self.assertEqual(terlihat, ['uji-a'])

    def test_pengelola_terpagar_perusahaan(self):
        """Pagar tenant untuk pengelola tetap ada, walaupun milik sendiri tidak."""
        self._dua_presensi()
        perusahaan_lain = self.env['res.company'].create({'name': 'Tenant Lain'})
        self.Log.sudo().create({
            'external_id': 7199, 'work_date': '2026-09-21',
            'employee_nopeg': 'uji-b', 'company_id': perusahaan_lain.id,
        })
        pengelola = self._pengguna(
            'uji.pengelola.pagar',
            groups=[self.env.ref('base.group_user'),
                    self.env.ref('presenly_saas.group_presenly_saas_manager')],
        )

        self.assertEqual(self.Log.with_user(pengelola).search_count([]), 2)
        self.assertEqual(
            sorted(self.Log.with_user(pengelola).search([]).mapped('employee_nopeg')),
            ['uji-a', 'uji-b'],
        )

    # ------------------------------------------------------------------
    # Kepemilikan aturan
    # ------------------------------------------------------------------
    def test_aturan_milik_sendiri_ada_dan_berlaku_untuk_pengguna_internal(self):
        model = self.env['ir.model'].search(
            [('model', 'in', ['presenly.saas.attendance.log', 'presenly.saas.overtime'])],
        )
        aturan = self.env['ir.rule'].search([
            ('model_id', 'in', model.ids),
            ('name', 'like', 'own rows only'),
        ])

        self.assertEqual(len(aturan), 2)
        for satu in aturan:
            self.assertIn(
                self.env.ref('base.group_user'), satu.groups,
                '%s harus berlaku untuk pengguna internal' % satu.name,
            )

    def test_aturan_cabang_tidak_lagi_untuk_pengguna_internal(self):
        """Kalau grup internal dikembalikan, aturan milik sendiri jadi tidak berarti.

        Aturan grup digabung dengan OR, jadi satu aturan cabang yang masih
        menyebut pengguna internal cukup untuk membuat semua rekan sekerja
        terlihat kembali.
        """
        aturan = self.env['ir.rule'].search([
            ('name', 'like', 'own branch only'),
            ('model_id.model', 'in', [
                'presenly.saas.leave', 'presenly.saas.overtime',
                'presenly.saas.medical.certificate',
                'presenly.saas.attendance.correction',
                'presenly.saas.shift.swap',
            ]),
        ])

        self.assertEqual(len(aturan), 5, 'aturan cabang kelima pengajuan harus ada')
        for satu in aturan:
            self.assertNotIn(
                self.env.ref('base.group_user'), satu.groups,
                '%s masih berlaku untuk pengguna internal' % satu.name,
            )
            self.assertIn(
                self.env.ref('presenly_saas_hr.group_presenly_saas_approver'),
                satu.groups,
                '%s harus berlaku untuk Approver' % satu.name,
            )
