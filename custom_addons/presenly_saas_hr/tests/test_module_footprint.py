from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPresenlyModuleFootprint(TransactionCase):
    """Batas modul: pegawai memakai HR native, absensi dan cuti tidak.

    Modul ini mencerminkan absensi dan cuti dari Presenly. Kalau
    ``hr_attendance`` atau ``hr_holidays`` aktif bersamaan, satu kejadian
    tercatat dua kali dan tidak jelas mana yang benar. Karena itu keduanya
    dikecualikan, dan tes ini menjaga pengecualian itu tidak hilang diam-diam.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = cls.env['ir.module.module'].search(
            [('name', '=', 'presenly_saas_hr')], limit=1
        )
        cls.Module = cls.env['ir.module.module']

    def test_mengecualikan_absensi_dan_cuti_native(self):
        self.assertEqual(
            sorted(self.module.exclusion_ids.mapped('name')),
            ['hr_attendance', 'hr_holidays'],
        )

    def test_modul_yang_dikecualikan_benar_benar_ada(self):
        # Kalau namanya salah ketik atau modulnya tidak ada, pengecualian ini
        # tidak akan pernah berbunyi dan pengamannya diam-diam mati.
        for name in ('hr_attendance', 'hr_holidays'):
            self.assertTrue(
                self.Module.search_count([('name', '=', name)]),
                'modul %s tidak terdaftar, pengecualian jadi tidak berguna' % name,
            )

    def test_pengecualian_tercatat_di_modul_ini(self):
        # Pengecualian disimpan di sisi modul ini, bukan di sisi modul yang
        # dikecualikan. Odoo memeriksanya dengan menelusuri seluruh modul yang
        # terpasang, jadi penolakannya tetap berlaku dua arah walaupun catatannya
        # hanya ada di sini.
        self.assertTrue(self.module.exclusion_ids)
        for exclusion in self.module.exclusion_ids:
            self.assertEqual(exclusion.module_id, self.module)

    def test_hr_inti_menjadi_dependensi(self):
        self.assertIn('hr', self.module.dependencies_id.mapped('name'))
        # Modul inti tidak boleh ikut menarik HR.
        core = self.Module.search([('name', '=', 'presenly_saas')], limit=1)
        self.assertNotIn('hr', core.dependencies_id.mapped('name'))
        self.assertEqual(
            self.Module.search([('name', '=', 'hr')], limit=1).state,
            'installed',
        )

    def test_tidak_menarik_absensi_atau_cuti_sebagai_dependensi(self):
        # `hr` inti tidak boleh membawa keduanya ikut terpasang.
        depends = set(self.module.dependencies_id.mapped('name'))
        for terlarang in ('hr_attendance', 'hr_holidays', 'hr_timesheet'):
            self.assertNotIn(terlarang, depends)

    def test_hr_employee_dapat_dipakai(self):
        # Bukti bahwa dependensi `hr` benar-benar bisa dipakai, bukan sekadar
        # tercatat di manifest: modelnya bisa dibaca dari sini.
        self.assertIn('name', self.env['hr.employee']._fields)
        self.assertTrue(self.env['hr.employee'].search([]) is not None)
