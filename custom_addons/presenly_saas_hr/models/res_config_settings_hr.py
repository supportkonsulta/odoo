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
    presenly_saas_allow_approval_from_odoo = fields.Boolean(
        string='Decide Requests from Odoo',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_allow_approval_from_odoo',
        groups='presenly_saas.group_presenly_saas_manager',
    )
    presenly_saas_push_work_locations = fields.Boolean(
        string='Send Work Location Edits to Presenly',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_push_work_locations',
        groups='presenly_saas.group_presenly_saas_manager',
    )
    presenly_saas_sync_employee_placements = fields.Boolean(
        string='Apply Employee Placements',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_sync_employee_placements',
        groups='presenly_saas.group_presenly_saas_manager',
    )
    presenly_saas_fill_usual_location = fields.Boolean(
        string='Fill Usual Work Location from the Pattern',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_fill_usual_location',
        groups='presenly_saas.group_presenly_saas_manager',
    )
    presenly_saas_sync_work_locations = fields.Boolean(
        string='Sync Work Locations to Odoo',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_sync_work_locations',
        groups='presenly_saas.group_presenly_saas_manager',
    )
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

        Kesalahan yang sama terulang saat `sync_work_locations` ditambahkan: field
        dan inversenya ditulis, pengisiannya terlupa. Karena itu setiap field
        setelan baru wajib mengisi dirinya di sini juga.
        """
        super()._compute_presenly_saas()
        for settings in self:
            config = settings._presenly_saas_config()
            settings.presenly_saas_fill_usual_location = (
                config.fill_usual_location if config else False
            )
            settings.presenly_saas_sync_work_locations = (
                config.sync_work_locations if config else False
            )
            settings.presenly_saas_allow_approval_from_odoo = (
                config.allow_approval_from_odoo if config else False
            )
            settings.presenly_saas_push_work_locations = (
                config.push_work_locations if config else False
            )
            settings.presenly_saas_sync_employee_placements = (
                config.sync_employee_placements if config else False
            )
            settings.presenly_saas_webhook_enabled = config.webhook_enabled if config else False
            settings.presenly_saas_webhook_url = config.webhook_url if config else False
            settings.presenly_saas_webhook_last_received_at = (
                config.webhook_last_received_at if config else False
            )

    def _inverse_presenly_saas_allow_approval_from_odoo(self):
        self._write_presenly_saas_config(
            {'allow_approval_from_odoo': self.presenly_saas_allow_approval_from_odoo}
        )

    def _inverse_presenly_saas_push_work_locations(self):
        self._write_presenly_saas_config(
            {'push_work_locations': self.presenly_saas_push_work_locations}
        )

    def _inverse_presenly_saas_sync_employee_placements(self):
        self._write_presenly_saas_config(
            {'sync_employee_placements': self.presenly_saas_sync_employee_placements}
        )

    def _inverse_presenly_saas_fill_usual_location(self):
        self._write_presenly_saas_config(
            {'fill_usual_location': self.presenly_saas_fill_usual_location}
        )

    def _inverse_presenly_saas_sync_work_locations(self):
        self._write_presenly_saas_config(
            {'sync_work_locations': self.presenly_saas_sync_work_locations}
        )

    def _inverse_presenly_saas_webhook_enabled(self):
        # Hanya menyalakan niatnya. Pendaftaran alamatnya sendiri dilakukan
        # tombol Register, karena butuh alamat yang bisa dijangkau server —
        # dan itu baru diketahui saat dijalankan, bukan saat halaman disimpan.
        self._write_presenly_saas_config(
            {'webhook_enabled': bool(self.presenly_saas_webhook_enabled)}
        )

