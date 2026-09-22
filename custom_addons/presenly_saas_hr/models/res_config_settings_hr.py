from odoo import api, fields, models

MANAGER_GROUP = 'presenly_saas.group_presenly_saas_manager'


class ResConfigSettings(models.TransientModel):
    """Blok pemberitahuan perubahan, di modul jembatan.

    Ada di sini karena peristiwanya hanya soal pegawai: tanpa `hr`, tidak ada
    yang perlu diberitahukan.
    """

    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    # Pemberitahuan perubahan (webhook)
    # ------------------------------------------------------------------
    presenly_saas_webhook_enabled = fields.Boolean(
        string='Send Change Notifications',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_webhook_enabled',
        groups=MANAGER_GROUP,
    )
    presenly_saas_webhook_url = fields.Char(
        string='Webhook URL',
        compute='_compute_presenly_saas',
        groups=MANAGER_GROUP,
    )
    presenly_saas_webhook_last_received_at = fields.Datetime(
        string='Last Notification Received',
        compute='_compute_presenly_saas',
        groups=MANAGER_GROUP,
    )


    @api.depends('company_id')
    def _compute_presenly_saas(self):
        """Isi field webhook, di atas isi field inti.

        Tiga field di atas memakai compute milik modul inti. Saat modul ini
        memisahkan diri, definisi fieldnya ikut pindah tetapi pengisiannya
        tertinggal, sehingga fieldnya dideklarasikan ber-compute tanpa ada yang
        mengisinya. Gejalanya baru muncul saat halaman Settings dibuka:
        "Compute method failed to assign ...presenly_saas_webhook_url".
        """
        super()._compute_presenly_saas()
        for settings in self:
            config = settings._presenly_saas_config()
            settings.presenly_saas_webhook_enabled = config.webhook_enabled if config else False
            settings.presenly_saas_webhook_url = config.webhook_url if config else False
            settings.presenly_saas_webhook_last_received_at = (
                config.webhook_last_received_at if config else False
            )

    def _inverse_presenly_saas_webhook_enabled(self):
        # Hanya menyalakan niatnya. Pendaftaran alamatnya sendiri dilakukan
        # tombol Register, karena butuh alamat yang bisa dijangkau server —
        # dan itu baru diketahui saat dijalankan, bukan saat halaman disimpan.
        self._write_presenly_saas_config(
            {'webhook_enabled': bool(self.presenly_saas_webhook_enabled)}
        )

