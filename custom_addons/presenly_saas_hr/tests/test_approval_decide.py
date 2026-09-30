from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.presenly_saas.services.saas_client import SaasClientError


@tagged('post_install', '-at_install')
class TestPresenlyApprovalDecide(TransactionCase):
    """Tombol keputusan: siapa yang melihatnya, dan apa yang dikirim.

    Yang dijaga tes ini adalah hal-hal yang mahal kalau salah:

    1. Tombol hanya muncul untuk orang yang menurut langkah persetujuan berhak —
       dan pencocokannya memakai nopeg, bukan nama.
    2. Level bertipe `direct_manager` dicocokkan lewat atasan pemohon, yang sudah
       disalin dari Presenly; level bertipe `role`/`permission` tidak menunjuk
       siapa pun karena yang berhak sekumpulan orang.
    3. Yang dikirim adalah keputusan, bukan wewenang: server tetap memeriksa, dan
       penolakannya ditampilkan.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.config.write({
            'enabled': True, 'active': True,
            # Menyala secara bawaan di berkas ini: yang diuji perilaku
            # keputusannya. Uji yang membuktikan perilaku saat mati
            # menyalakannya sendiri.
            'allow_approval_from_odoo': True,
        })
        cls.Leave = cls.env['presenly.saas.leave']
        cls.Step = cls.env['presenly.saas.approval.step.leave']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)
        cls._urutan = 0

    def setUp(self):
        super().setUp()
        # Penyegaran sebelum/sesudah keputusan diuji terpisah; di sini yang
        # diperiksa jalur keputusannya, jadi jaringannya tidak disentuh.
        self.segar = mock.Mock(return_value='')
        patch = mock.patch.object(
            type(self.config), '_refresh_recent_from_decision', self.segar,
        )
        patch.start()
        self.addCleanup(patch.stop)

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------
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
                'login': 'uji-%s-%s' % (nopeg, self._urutan),
                'email': '%s@example.com' % nopeg,
                # Seperti akun sungguhan: pengguna internal, dan memegang grup
                # Approver - itulah yang membuatnya boleh membaca pengajuan
                # cabangnya. Tanpa keduanya, tombol keputusannya tidak akan
                # pernah terlihat, dan ujinya menguji keadaan yang tidak ada.
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('presenly_saas_hr.group_presenly_saas_approver').id,
                ])],
            })
            pegawai.user_id = akun
        return pegawai

    def _pengajuan(self, pemohon_nopeg, level=1, langkah=()):
        self._urutan += 1
        pengajuan = self.Leave.create({
            'external_id': 9000 + self._urutan,
            'reference_number': 'CUTI-%s' % self._urutan,
            'employee_nopeg': pemohon_nopeg,
            'employee_name': 'Pemohon',
            'status': 'pending',
            'approval_current_level': level,
            'approval_total_levels': 2,
            # Cabangnya diisi: approver membaca pengajuan lewat aturan cabang,
            # dan baris tanpa cabang memang hanya terlihat pengelola dan HR.
            'tenant_client_company_id': self.env.company.id,
        })
        for nomor, tipe, nopeg in langkah:
            self.Step.create({
                'leave_id': pengajuan.id,
                'level': nomor,
                'approver_type': tipe,
                'expected_nopeg': nopeg,
                'step_status': 'pending',
            })
        return pengajuan

    # ------------------------------------------------------------------
    # Pencocokan approver
    # ------------------------------------------------------------------
    def test_level_bertipe_user_dicocokkan_lewat_nopeg(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])

        # Diperiksa tidak kosong lebih dulu: dua recordset kosong juga "sama",
        # sehingga asersi kesamaan saja bisa lulus tanpa approvernya ketemu.
        self.assertTrue(pengajuan.presenly_odoo_approver_id, 'approvernya harus ketemu')
        self.assertEqual(pengajuan.presenly_odoo_approver_id, approver.user_id)
        self.assertTrue(
            pengajuan.with_user(approver.user_id).presenly_can_decide,
            'yang berhak melihat tombolnya adalah approver itu sendiri',
        )

    def test_pengguna_lain_tidak_bisa_memutuskan(self):
        self._pegawai('uji-approver', 'Feri', pengguna=True)
        lain = self._pegawai('uji-lain', 'Orang Lain', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])

        self.assertFalse(pengajuan.with_user(lain.user_id).presenly_can_decide)

    def test_level_bertipe_atasan_langsung_memakai_atasan_pemohon(self):
        """Atasan itu bergantung pada pemohonnya, dan sudah disalin dari Presenly."""
        atasan = self._pegawai('uji-atasan', 'Yusril', pengguna=True)
        self._pegawai('uji-pemohon', 'Rangga', atasan=atasan, pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', level=2, langkah=[(2, 'direct_manager', False)])

        self.assertTrue(pengajuan.presenly_odoo_approver_id, 'atasannya harus ketemu')
        self.assertEqual(pengajuan.presenly_odoo_approver_id, atasan.user_id)

    def test_level_bertipe_role_tidak_menunjuk_siapa_pun(self):
        """Yang berhak sekumpulan orang, jadi tidak ada satu orang untuk ditunjuk."""
        self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'role', 'Supervisor')])

        self.assertFalse(pengajuan.presenly_odoo_approver_id)
        self.assertFalse(pengajuan.presenly_can_decide)

    def test_langkah_yang_sudah_diputuskan_tidak_lagi_menunjuk_approver(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        pengajuan.approval_step_ids.write({'acted_at': '2026-09-01 08:00:00'})

        self.assertFalse(
            pengajuan.presenly_odoo_approver_id,
            'level yang sudah diputuskan tidak lagi menunggu siapa pun',
        )

    def test_approver_tanpa_akun_odoo_tidak_bisa_memutuskan(self):
        self._pegawai('uji-approver', 'Feri', pengguna=False)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])

        self.assertFalse(pengajuan.presenly_odoo_approver_id)
        self.assertFalse(pengajuan.presenly_can_decide)

    # ------------------------------------------------------------------
    # Kesegaran keadaan, dan syarat tombolnya
    # ------------------------------------------------------------------
    def test_formulir_menyegarkan_sebelum_dibaca(self):
        """Membuka satu pengajuan harus menampilkan keadaan yang sekarang.

        Daftar sudah disegarkan lewat `web_search_read`; formulir membacanya
        lewat jalur lain, dan tanpa penimpaan itu status serta levelnya bisa
        sudah lewat tanpa ada yang menyadarinya.
        """
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])

        with mock.patch.object(
            type(self.config), '_refresh_from_page', mock.Mock(),
        ) as segar:
            pengajuan.with_user(approver.user_id).web_read({'status': {}})

        segar.assert_called_once_with('leaves')

    def test_formulir_dibaca_lewat_jalur_rpc_klien(self):
        """Klien web memanggilnya dengan daftar id sebagai argumen pertama.

        Uji sebelumnya memanggil metodenya langsung, dan justru itu sebabnya
        kesalahan dekorasi lolos: `call_kw` memisahkan argumen pertama hanya
        untuk metode yang bukan `@api.model`. Dengan `@api.model`, daftar id ikut
        masuk sebagai argumen - dan pemanggilan dari peramban gagal walaupun
        ujinya hijau.
        """
        from odoo.service.model import call_kw

        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])

        hasil = call_kw(
            self.Leave.with_user(approver.user_id), 'web_read',
            [[pengajuan.id], {'status': {}}], {},
        )

        self.assertEqual(hasil[0]['id'], pengajuan.id)
        self.assertEqual(hasil[0]['status'], 'pending')

    def test_pembacaan_banyak_baris_tidak_menyegarkan(self):
        """Menarik data untuk sebelas baris bukan membuka satu formulir."""
        banyak = self.Leave.browse()
        for _nomor in range(11):
            banyak |= self._pengajuan('uji-pemohon')

        with mock.patch.object(
            type(self.config), '_refresh_from_page', mock.Mock(),
        ) as segar:
            banyak.web_read({'status': {}})

        self.assertEqual(len(banyak), 11, 'prasyarat tes: lebih dari batasnya')
        segar.assert_not_called()

    def test_tombol_muncul_hanya_bila_keputusannya_bisa_dikirim(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        self.assertTrue(pengajuan.with_user(approver.user_id).presenly_can_decide)
        self.assertFalse(pengajuan.with_user(approver.user_id).presenly_decide_hint)

    def test_setelan_mati_menyembunyikan_tombol_dan_menjelaskan(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': False})

        dilihat = pengajuan.with_user(approver.user_id)

        self.assertFalse(dilihat.presenly_can_decide)
        self.assertIn('turned off', dilihat.presenly_decide_hint)

    def test_tanpa_nopeg_tombolnya_hilang_dan_alasannya_ditulis(self):
        """Pesan yang dulu muncul setelah tombol ditekan, sekarang sebelum.

        Levelnya bertipe atasan langsung, karena approver bertipe `user`
        dicocokkan lewat nopeg - dan tanpa nopeg ia memang tidak bisa ditunjuk.
        """
        atasan = self._pegawai('', 'Atasan Tanpa Nopeg', pengguna=True)
        self._pegawai('uji-pemohon', 'Pemohon', atasan=atasan)
        pengajuan = self._pengajuan(
            'uji-pemohon', langkah=[(1, 'direct_manager', None)],
        )

        dilihat = pengajuan.with_user(atasan.user_id)

        self.assertEqual(dilihat.presenly_odoo_approver_id, atasan.user_id)
        self.assertFalse(dilihat.presenly_can_decide)
        self.assertIn('nopeg', dilihat.presenly_decide_hint.lower())

    def test_pengguna_lain_tidak_diberi_penjelasan(self):
        """Yang tidak berhak tidak mencari tombolnya, jadi tidak perlu alasan."""
        self._pegawai('uji-approver', 'Feri', pengguna=True)
        lain = self._pegawai('uji-lain', 'Orang Lain', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        dilihat = pengajuan.with_user(lain.user_id)

        self.assertFalse(dilihat.presenly_can_decide)
        self.assertFalse(dilihat.presenly_decide_hint)

    def test_kelima_jenis_pengajuan_dilayani(self):
        """Nama resourcenya harus sama dengan yang dilayani backend.

        Salah satu huruf keliru membuat tombolnya muncul lalu ditolak dengan
        alasan yang menyesatkan, atau tidak muncul sama sekali.
        """
        from odoo.addons.presenly_saas_hr.models.presenly_saas_approval_hr import (
            RESOURCE_BY_MODEL,
        )

        self.assertEqual(RESOURCE_BY_MODEL, {
            'presenly.saas.leave': 'leaves',
            'presenly.saas.overtime': 'overtimes',
            'presenly.saas.medical.certificate': 'medical-certificates',
            'presenly.saas.attendance.correction': 'attendance-corrections',
            'presenly.saas.shift.swap': 'shift-swaps',
        })

        # Dan barisnya benar-benar melaporkan resource itu, bukan hanya terdaftar.
        self._pegawai('uji-approver', 'Feri', pengguna=True)
        self.assertEqual(
            self._pengajuan('uji-pemohon')._presenly_resource(), 'leaves',
        )

    def test_setiap_form_punya_tombol_keputusan(self):
        from lxml import etree
        for nama_view in (
            'view_presenly_saas_leave_form_decide',
            'view_presenly_saas_overtime_form_decide',
            'view_presenly_saas_medical_certificate_form_decide',
            'view_presenly_saas_attendance_correction_form_decide',
            'view_presenly_saas_shift_swap_form_decide',
        ):
            arch = etree.fromstring(
                self.env.ref('presenly_saas_hr.%s' % nama_view).arch
            )
            for tombol in ('action_presenly_approve', 'action_presenly_reject'):
                self.assertTrue(
                    arch.xpath("//button[@name='%s']" % tombol),
                    '%s tidak punya tombol %s' % (nama_view, tombol),
                )
            self.assertTrue(
                arch.xpath("//field[@name='presenly_decide_hint']"),
                '%s tidak punya catatan alasannya' % nama_view,
            )

    def _lembur(self, approver_nopeg='uji-approver'):
        self._urutan += 1
        lembur = self.env['presenly.saas.overtime'].create({
            'external_id': 9200 + self._urutan,
            'overtime_date': '2026-09-21',
            'employee_nopeg': 'uji-pemohon',
            'status': 'pending',
            'approval_current_level': 1,
            # Cabangnya diisi seperti pada cuti: approver membaca pengajuan lewat
            # aturan cabang, dan baris tanpa cabang hanya terlihat pengelola & HR.
            'tenant_client_company_id': self.env.company.id,
        })
        self.env['presenly.saas.approval.step.overtime'].create({
            'overtime_id': lembur.id,
            'level': 1,
            'approver_type': 'user',
            'expected_nopeg': approver_nopeg,
            'step_status': 'pending',
        })
        return lembur

    def test_lembur_mengirim_resourcenya_sendiri(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        lembur = self._lembur()

        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        with patch_klien, patch_tarik:
            lembur.with_user(approver.user_id).action_presenly_approve()

        resource, submission_id, isi = klien.decide_submission.call_args[0]
        self.assertEqual(resource, 'overtimes')
        self.assertEqual(submission_id, lembur.external_id)
        self.assertEqual(isi['level'], 1)


    # ------------------------------------------------------------------
    # Kabar ke layar yang sedang terbuka
    # ------------------------------------------------------------------
    def _pesan_bus(self):
        """Pesan bus yang menunggu dikirim di transaksi ini."""
        return [
            nilai for nilai in self.env.cr.precommit.data.get('bus.bus.values', [])
            if 'presenly_saas_submission' in (nilai.get('message') or '')
        ]

    def test_perubahan_status_mengabari_pemohon_dan_approver(self):
        """Yang dikabari hanya yang berkepentingan, bukan semua pengguna."""
        pemohon = self._pegawai('uji-pemohon', 'Pemohon', pengguna=True)
        self._pegawai('uji-approver', 'Feri', pengguna=True)
        # Dua level, supaya yang berjalan di level 2 punya pemegangnya: tanpa
        # langkahnya, tidak ada yang ditunjuk dan tidak ada yang dikabari.
        pengajuan = self._pengajuan('uji-pemohon', langkah=[
            (1, 'user', 'uji-approver'),
            (2, 'user', 'uji-approver'),
        ])
        pengajuan.write({'hr_employee_id': pemohon.id})

        pengajuan.write({'status': 'pending', 'approval_current_level': 2})

        pesan = self._pesan_bus()
        self.assertEqual(len(pesan), 2, 'pemohon dan approver, bukan lebih')

        # Isinya diperiksa sebagai data, bukan sebagai teks: yang dikirim memang
        # data, dan kalimatnya disusun di sisi klien.
        import json

        isi = json.loads(pesan[0]['message'])
        self.assertEqual(isi['type'], 'presenly_saas_submission')
        self.assertEqual(isi['payload']['model'], 'presenly.saas.leave')
        self.assertEqual(isi['payload']['id'], pengajuan.id)
        self.assertEqual(isi['payload']['level'], 2)
        self.assertEqual(isi['payload']['total_levels'], 2)

    def test_penulisan_yang_tidak_mengubah_keadaan_tidak_mengabari(self):
        """Tarikan menulis ulang barisnya; tanpa perubahan, tidak ada kabar."""
        self._pegawai('uji-pemohon', 'Pemohon', pengguna=True)
        self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan(
            'uji-pemohon', langkah=[(1, 'user', 'uji-approver')],
        )

        pengajuan.write({'status': 'pending', 'approval_current_level': 1})

        self.assertEqual(self._pesan_bus(), [])

    # ------------------------------------------------------------------
    # Mengirim keputusan
    # ------------------------------------------------------------------
    def _dengan_klien_tiruan(self):
        klien = mock.Mock()
        klien.decide_submission = mock.Mock(return_value={'data': {'id': 1}})
        return mock.patch.object(
            type(self.config), '_client', lambda self: klien
        ), mock.patch.object(
            type(self.config), '_pull_recent_data', lambda self, *a, **k: ({}, False)
        ), klien

    def test_tombol_mengirim_keputusan_ke_presenly(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        with patch_klien, patch_tarik:
            pengajuan.with_user(approver.user_id).action_presenly_approve()

        klien.decide_submission.assert_called_once()
        resource, submission_id, isi = klien.decide_submission.call_args[0]
        self.assertEqual(resource, 'leaves')
        self.assertEqual(submission_id, pengajuan.external_id)
        self.assertEqual(isi, {
            'actor_nopeg': 'uji-approver', 'decision': 'approve', 'level': 1,
        })

    def test_setelan_mati_menolak_dengan_pesan(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': False})

        with self.assertRaises(UserError):
            pengajuan.with_user(approver.user_id).action_presenly_approve()

    def test_pengguna_tanpa_nopeg_ditolak(self):
        """Presenly mengenali siapa yang memutuskan lewat nopeg."""
        self._pegawai('uji-approver', 'Feri', pengguna=True)
        tanpa_nopeg = self._pegawai('', 'Tanpa Nopeg', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        with self.assertRaises(UserError) as galat:
            pengajuan.with_user(tanpa_nopeg.user_id).action_presenly_approve()
        self.assertIn('nopeg', str(galat.exception).lower())

    def test_yang_bukan_approver_ditolak_sebelum_mengirim(self):
        self._pegawai('uji-approver', 'Feri', pengguna=True)
        lain = self._pegawai('uji-lain', 'Orang Lain', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        with patch_klien, patch_tarik:
            with self.assertRaises(UserError):
                pengajuan.with_user(lain.user_id).action_presenly_approve()

        klien.decide_submission.assert_not_called()

    def test_penolakan_server_disegarkan_dan_layarnya_disegarkan(self):
        """Ditolak berarti salinan kita tertinggal, jadi layarnya yang diperbaiki.

        Sebelumnya jalur ini melempar `UserError`: pesannya terlihat, tetapi
        layarnya tetap menampilkan keadaan yang baru saja dibantah server, dan
        `UserError` membatalkan transaksi sehingga penyegaran pun ikut hilang.
        """
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        klien.decide_submission.side_effect = SaasClientError('Level yang berjalan 2, bukan 1.')
        with patch_klien, patch_tarik:
            hasil = pengajuan.with_user(approver.user_id).action_presenly_approve()

        self.assertEqual(hasil['tag'], 'presenly_saas.notice')
        self.assertEqual(hasil['params']['kind'], 'warning')
        self.assertIn('Level yang berjalan 2, bukan 1.', hasil['params']['body'])
        self.assertTrue(hasil['params']['reload'])
        self.assertEqual(self.segar.call_count, 2, 'sekali sebelum, sekali sesudah ditolak')

    def test_keadaan_disegarkan_sebelum_keputusan_dikirim(self):
        """Levelnya dibaca ulang sesudah disegarkan, bukan dari salinan basi."""
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        urutan = []
        self.segar.side_effect = lambda: urutan.append('segar') or ''
        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        klien.decide_submission.side_effect = lambda *a, **k: urutan.append('kirim')
        with patch_klien, patch_tarik:
            pengajuan.with_user(approver.user_id).action_presenly_approve()

        self.assertEqual(urutan, ['segar', 'kirim'])

    def test_pengajuan_yang_sudah_diputuskan_tidak_mengirim_apa_pun(self):
        """Setelah disegarkan, bisa jadi tidak ada lagi yang menunggu diputuskan."""
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan(
            'uji-pemohon', level=False, langkah=[(1, 'user', 'uji-approver')],
        )
        pengajuan.write({'status': 'approved'})
        self.config.write({'allow_approval_from_odoo': True})

        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        with patch_klien, patch_tarik:
            hasil = pengajuan.with_user(approver.user_id).action_presenly_approve()

        klien.decide_submission.assert_not_called()
        self.assertIn('no longer waiting', hasil['params']['body'])
        self.assertTrue(hasil['params']['reload'])

    def test_menolak_mengirim_keputusan_reject(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        with patch_klien, patch_tarik:
            pengajuan.with_user(approver.user_id).action_presenly_reject()

        self.assertEqual(klien.decide_submission.call_args[0][2]['decision'], 'reject')
