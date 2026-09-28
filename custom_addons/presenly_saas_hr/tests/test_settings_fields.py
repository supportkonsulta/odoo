from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPresenlySettingsFields(TransactionCase):
    """Setiap field setelan kita harus benar-benar terisi saat dibaca.

    Ini pernah terlewat. Saat integrasi pegawai dipisahkan ke modul ini, tiga
    field webhook ikut pindah tetapi pengisiannya tertinggal, sehingga fieldnya
    ber-compute tanpa ada yang mengisinya. Tes lain tidak menangkapnya karena
    tidak ada yang membaca field itu; gejalanya baru muncul di layar, saat
    halaman Settings dibuka:

        ValueError: Compute method failed to assign
          res.config.settings(,).presenly_saas_webhook_url

    Membaca fieldnya di sini memicu compute yang sama seperti yang dijalankan
    UI, jadi kekurangan semacam ini ketahuan sebelum sampai ke pengguna.
    """

    def test_semua_field_setelan_dapat_dibaca(self):
        settings = self.env['res.config.settings'].create({})
        nama = sorted(
            nama for nama in self.env['res.config.settings']._fields
            if nama.startswith('presenly_saas_')
        )
        self.assertTrue(nama, 'tidak ada field setelan Presenly')
        for field_name in nama:
            # Membaca saja sudah cukup: compute yang tidak mengisi fieldnya akan
            # menaikkan ValueError di sini.
            settings[field_name]

    def test_field_webhook_terbaca_saat_config_belum_ada(self):
        # Keadaan paling mudah memicu galat: company belum punya konfigurasi.
        config = self.env['presenly.saas.config'].search([
            ('company_id', '=', self.env.company.id),
        ])
        config.unlink()
        settings = self.env['res.config.settings'].create({})
        self.assertFalse(settings.presenly_saas_webhook_enabled)
        self.assertFalse(settings.presenly_saas_webhook_url)
        self.assertFalse(settings.presenly_saas_webhook_last_received_at)

    def test_field_webhook_terbaca_dari_config_yang_ada(self):
        config = self.env['presenly.saas.config']._get_or_create(self.env.company)
        config.write({
            'webhook_enabled': True,
            'webhook_url': 'https://odoo.example.com/presenly_saas/webhook/token',
        })
        settings = self.env['res.config.settings'].create({})
        self.assertTrue(settings.presenly_saas_webhook_enabled)
        self.assertEqual(
            settings.presenly_saas_webhook_url,
            'https://odoo.example.com/presenly_saas/webhook/token',
        )
