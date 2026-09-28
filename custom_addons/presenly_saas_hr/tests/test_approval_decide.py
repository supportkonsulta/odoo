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
        cls.config.write({'enabled': True, 'active': True})
        cls.Leave = cls.env['presenly.saas.leave']
        cls.Step = cls.env['presenly.saas.approval.step.leave']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)
        cls._urutan = 0

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

    def test_penolakan_server_ditampilkan_apa_adanya(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        klien.decide_submission.side_effect = SaasClientError('Level yang berjalan 2, bukan 1.')
        with patch_klien, patch_tarik:
            with self.assertRaises(UserError) as galat:
                pengajuan.with_user(approver.user_id).action_presenly_approve()

        self.assertIn('Level yang berjalan 2, bukan 1.', str(galat.exception))

    def test_menolak_mengirim_keputusan_reject(self):
        approver = self._pegawai('uji-approver', 'Feri', pengguna=True)
        pengajuan = self._pengajuan('uji-pemohon', langkah=[(1, 'user', 'uji-approver')])
        self.config.write({'allow_approval_from_odoo': True})

        patch_klien, patch_tarik, klien = self._dengan_klien_tiruan()
        with patch_klien, patch_tarik:
            pengajuan.with_user(approver.user_id).action_presenly_reject()

        self.assertEqual(klien.decide_submission.call_args[0][2]['decision'], 'reject')
