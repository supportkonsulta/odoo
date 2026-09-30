from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPresenlyAclCoverage(TransactionCase):
    """Setiap model kita harus punya hak akses.

    Ini pernah terlewat: empat model Fase 1 (`attendance.log`,
    `pull.wizard`) tidak punya baris ACL
    sama sekali. Akibatnya bukan galat, melainkan **menu yang hilang** — Odoo
    menyembunyikan menu yang modelnya tidak boleh dibaca pengguna — dan wizard
    penarikan tidak bisa dipakai siapa pun selain superuser.

    Tes lain tidak menangkapnya karena semuanya berjalan sebagai superuser, yang
    melewati pemeriksaan hak akses. Karena itu pemeriksaannya dilakukan di sini,
    terhadap data, bukan terhadap perilaku.
    """

    def test_setiap_model_punya_hak_akses(self):
        models = self.env['ir.model'].search([('model', 'like', 'presenly.saas%')])
        self.assertTrue(models, 'tidak ada model presenly.saas yang terdaftar')

        tanpa_acl = []
        for model in models:
            # Model abstrak tidak punya tabel, jadi memang tidak boleh punya
            # baris ACL. `presenly.saas.guard` dan `...mirror.mixin` termasuk
            # di sini, dan keduanya bukan kekurangan.
            if self.env[model.model]._abstract:
                continue
            if not self.env['ir.model.access'].search_count([('model_id', '=', model.id)]):
                tanpa_acl.append(model.model)

        self.assertEqual(
            tanpa_acl, [],
            'model tanpa hak akses sama sekali: %s' % ', '.join(tanpa_acl),
        )

    def test_pengguna_internal_dapat_membaca_semua_cermin(self):
        # Tanpa ini, menunya disembunyikan Odoo dan pengguna melihat aplikasi
        # yang isinya kosong.
        group_user = self.env.ref('base.group_user')
        for nama in (
            'presenly.saas.attendance.log',
            'presenly.saas.subscription',
            'presenly.saas.timesheet',
            'presenly.saas.project',
            'presenly.saas.leave',
            'presenly.saas.sync.log',
        ):
            model = self.env['ir.model'].search([('model', '=', nama)], limit=1)
            self.assertTrue(model, 'model %s tidak terdaftar' % nama)
            boleh_baca = self.env['ir.model.access'].search_count([
                ('model_id', '=', model.id),
                ('group_id', '=', group_user.id),
                ('perm_read', '=', True),
            ])
            self.assertTrue(boleh_baca, 'pengguna internal tidak boleh membaca %s' % nama)

    def test_wizard_penarikan_dapat_dipakai(self):
        # Wizard perlu create, bukan hanya read: tanpa itu menunya muncul tetapi
        # membukanya gagal.
        wizard = self.env['ir.model'].search(
            [('model', '=', 'presenly.saas.pull.wizard')], limit=1
        )
        boleh = self.env['ir.model.access'].search([
            ('model_id', '=', wizard.id),
            ('group_id', '=', self.env.ref('base.group_user').id),
        ])
        self.assertTrue(boleh, 'wizard tidak punya hak akses')

    def test_cermin_presensi_terpagar_perusahaan(self):
        """Cermin presensi tidak boleh membiarkan perusahaan lain terlihat.

        Model ini dulu tidak punya aturan sama sekali, dan Odoo tidak menambahkan
        saringan perusahaan sendiri: `company_ids` hanya variabel yang bisa
        dipakai di domain. Akibatnya baris dari semua perusahaan terlihat oleh
        pengguna internal mana pun yang membuka daftarnya.

        Yang diperiksa di sini pagarnya, bukan siapa pemegangnya: modul HR
        memindahkan grupnya ke Approver dan menambahkan aturan "milik sendiri",
        jadi aturan ini memang berpindah tangan di pemasangan yang memakai HR.
        """
        model = self.env['ir.model'].search(
            [('model', '=', 'presenly.saas.attendance.log')], limit=1,
        )
        aturan = self.env['ir.rule'].search([('model_id', '=', model.id)])
        pagar = aturan.filtered(
            lambda satu: 'company_id' in (satu.domain_force or '')
            and 'company_ids' in (satu.domain_force or '')
        )
        self.assertTrue(pagar, 'tidak ada pagar perusahaan pada cermin presensi')

        pemegang = self.env.ref('base.group_user')
        approver = self.env.ref(
            'presenly_saas_hr.group_presenly_saas_approver', raise_if_not_found=False,
        )
        if approver:
            pemegang |= approver
        self.assertTrue(
            pagar.mapped('groups') & pemegang,
            'pagar perusahaan tidak dipegang grup mana pun',
        )

        manajer = self.env.ref('presenly_saas.group_presenly_saas_manager')
        self.assertIn(
            manajer, pagar.mapped('groups'),
            'pengelola harus melihat perusahaannya, bukan hanya miliknya',
        )

    def test_menyerahkan_hak_tulis_hanya_ke_manajer(self):
        # Cermin hanya boleh diubah oleh sinkronisasi, dan sinkronisasi berjalan
        # sebagai superuser. Pengguna biasa tidak perlu hak tulis.
        group_user = self.env.ref('base.group_user')
        for nama in ('presenly.saas.attendance.log',):
            model = self.env['ir.model'].search([('model', '=', nama)], limit=1)
            menulis = self.env['ir.model.access'].search_count([
                ('model_id', '=', model.id),
                ('group_id', '=', group_user.id),
                ('perm_write', '=', True),
            ])
            self.assertFalse(menulis, 'pengguna internal diberi hak tulis pada %s' % nama)
