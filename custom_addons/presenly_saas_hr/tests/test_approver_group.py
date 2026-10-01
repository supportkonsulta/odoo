from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPresenlyApproverGroup(TransactionCase):
    """Kelompok Approver dikelola sinkronisasi, bukan diisi tangan.

    Yang berhak ditentukan konfigurasi alur di Presenly. Kalau keanggotaannya
    diisi tangan di sini, salinan aturan itu akan berbeda pendapat dengan
    aslinya — dan yang paling mungkin terjadi adalah orang yang sudah dikeluarkan
    dari alur tetap bisa membuka menu permintaan.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Mirror = cls.env['presenly.saas.employee']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)
        cls.kelompok = cls.env.ref('presenly_saas_hr.group_presenly_saas_approver')

    def _pasangan(self, nopeg, efektif, dengan_akun=True):
        cermin = self.Mirror.create({
            'external_id': 6000 + abs(hash(nopeg)) % 1000,
            'nopeg': nopeg,
            'name': nopeg,
            'company_id': self.config.company_id.id,
            'can_approve_effective': efektif,
        })
        pegawai = self.Hr.create({'name': nopeg, 'presenly_nopeg': nopeg})
        akun = False
        if dengan_akun:
            akun = self.env['res.users'].create({
                'name': nopeg, 'login': 'akun-%s' % nopeg, 'email': '%s@example.com' % nopeg,
            })
            pegawai.user_id = akun
        cermin.hr_employee_id = pegawai.id
        return cermin, akun

    def test_kelompok_diberikan_kepada_yang_berhak(self):
        cermin, akun = self._pasangan('uji-berhak', efektif=True)

        self.Mirror._sync_approver_groups(cermin)

        self.assertIn(self.kelompok, akun.group_ids)

    def test_kelompok_dicabut_bila_tidak_lagi_berhak(self):
        cermin, akun = self._pasangan('uji-cabut', efektif=True)
        self.Mirror._sync_approver_groups(cermin)
        self.assertIn(self.kelompok, akun.group_ids)

        cermin.can_approve_effective = False
        self.Mirror._sync_approver_groups(cermin)

        self.assertNotIn(
            self.kelompok, akun.group_ids,
            'dikeluarkan dari alur berarti menunya ikut hilang',
        )

    def test_pegawai_tanpa_akun_dilewati(self):
        cermin, _akun = self._pasangan('uji-tanpa-akun', efektif=True, dengan_akun=False)

        self.Mirror._sync_approver_groups(cermin)

        self.assertFalse(cermin.hr_employee_id.user_id)

    def test_yang_tidak_berhak_tidak_diberi(self):
        cermin, akun = self._pasangan('uji-tidak-berhak', efektif=False)

        self.Mirror._sync_approver_groups(cermin)

        self.assertNotIn(self.kelompok, akun.group_ids)
