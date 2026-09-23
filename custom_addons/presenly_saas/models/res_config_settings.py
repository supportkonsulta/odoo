import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'presenly_saas.group_presenly_saas_manager'


class ResConfigSettings(models.TransientModel):
    """Blok Presenly SaaS di halaman Settings native Odoo.

    Ini satu-satunya tempat mengubah konfigurasi. Tidak ada form kedua yang
    mengedit data yang sama.

    Nilainya tetap tersimpan di `presenly.saas.config` (satu record per company),
    yaitu model yang sudah dibaca service, guard, cron, dan banner. Field di sini
    hanya jembatan: `compute` membaca record itu, `inverse` menuliskannya kembali.

    Setiap field punya inverse sendiri. Inverse bersama yang menulis semua field
    sekaligus akan berbahaya: pada penyimpanan sebagian, field yang tidak dikirim
    belum dihitung sehingga masih bernilai default, dan menulisnya akan menimpa
    tenant_code atau kunci API yang sebenarnya.
    """

    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    # Koneksi
    # ------------------------------------------------------------------
    presenly_saas_enabled = fields.Boolean(
        string='Connection Enabled',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_enabled',
        groups=MANAGER_GROUP,
    )
    presenly_saas_environment = fields.Selection(
        [('production', 'Production'), ('sandbox', 'Sandbox')],
        string='Environment',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_environment',
        groups=MANAGER_GROUP,
    )
    presenly_saas_base_url = fields.Char(
        string='Base URL',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_base_url',
        groups=MANAGER_GROUP,
    )
    presenly_saas_tenant_code = fields.Char(
        string='Tenant Code',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_tenant_code',
        groups=MANAGER_GROUP,
    )
    presenly_saas_api_key = fields.Char(
        string='API Key',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_api_key',
        groups=MANAGER_GROUP,
    )

    # ------------------------------------------------------------------
    # Keandalan
    # ------------------------------------------------------------------
    presenly_saas_timeout_seconds = fields.Integer(
        string='Timeout (seconds)',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_timeout_seconds',
        groups=MANAGER_GROUP,
    )
    presenly_saas_retry_count = fields.Integer(
        string='Retries',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_retry_count',
        groups=MANAGER_GROUP,
    )

    # ------------------------------------------------------------------
    # Kebijakan
    # ------------------------------------------------------------------
    presenly_saas_guard_mode = fields.Selection(
        [('off', 'Off'), ('warn', 'Warn only'), ('enforce', 'Enforce')],
        string='Guard Mode',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_guard_mode',
        groups=MANAGER_GROUP,
    )
    presenly_saas_grace_days = fields.Integer(
        string='Grace Period (days)',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_grace_days',
        groups=MANAGER_GROUP,
    )
    presenly_saas_show_banner = fields.Boolean(
        string='Show Banner',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_show_banner',
        groups=MANAGER_GROUP,
    )

    # ------------------------------------------------------------------
    # Penarikan terjadwal & jendela bergulir
    # ------------------------------------------------------------------
    presenly_saas_pull_months = fields.Integer(
        string='Months Pulled by Cron',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_pull_months',
        groups=MANAGER_GROUP,
    )
    presenly_saas_request_auto_refresh = fields.Boolean(
        string='Refresh on Open',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_request_auto_refresh',
        groups=MANAGER_GROUP,
    )
    presenly_saas_cron_sync_minutes = fields.Integer(
        string='Scheduled Refresh (minutes)',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_cron_sync_minutes',
        groups=MANAGER_GROUP,
    )
    presenly_saas_retention_months = fields.Integer(
        string='Retention (months)',
        compute='_compute_presenly_saas',
        inverse='_inverse_presenly_saas_retention_months',
        groups=MANAGER_GROUP,
    )

    # ------------------------------------------------------------------
    # Diagnostik: hanya dibaca, tidak pernah ditulis dari sini
    # ------------------------------------------------------------------
    presenly_saas_last_check_at = fields.Datetime(
        string='Last Check',
        compute='_compute_presenly_saas',
        groups=MANAGER_GROUP,
    )
    presenly_saas_last_check_status = fields.Selection(
        [('success', 'Success'), ('failed', 'Failed')],
        string='Last Check Status',
        compute='_compute_presenly_saas',
        groups=MANAGER_GROUP,
    )
    presenly_saas_last_check_message = fields.Text(
        string='Last Check Result',
        compute='_compute_presenly_saas',
        groups=MANAGER_GROUP,
    )

    # ------------------------------------------------------------------
    # Jembatan
    # ------------------------------------------------------------------
    def _presenly_saas_config(self):
        """Record konfigurasi company ini, atau recordset kosong bila belum ada.

        Sengaja hanya membaca. `compute` tidak boleh menulis, dan dulu helper ini
        memanggil `_get_or_create` sehingga sekadar membuka halaman Settings bisa
        membuat record baru.
        """
        self.ensure_one()
        return self.env['presenly.saas.config'].sudo().search(
            [('company_id', '=', self.company_id.id)], limit=1
        )

    def _presenly_saas_config_ensured(self):
        """Sama seperti di atas, tetapi membuat record bila belum ada.

        Dipakai oleh `inverse` dan tombol aksi, yaitu saat pengguna memang
        sedang menyimpan atau menjalankan sesuatu.
        """
        self.ensure_one()
        return self.env['presenly.saas.config']._get_or_create(self.company_id)

    @api.depends('company_id')
    def _compute_presenly_saas(self):
        Config = self.env['presenly.saas.config']
        config_fields = [
            'enabled', 'environment', 'base_url', 'tenant_code', 'api_key',
            'timeout_seconds', 'retry_count', 'guard_mode', 'grace_days', 'show_banner',
            'pull_months', 'retention_months', 'request_auto_refresh',
            'cron_sync_minutes',
        ]

        for settings in self:
            config = settings._presenly_saas_config()
            if config:
                values = {name: config[name] for name in config_fields}
                settings.presenly_saas_last_check_at = config.last_check_at
                settings.presenly_saas_last_check_status = config.last_check_status
                settings.presenly_saas_last_check_message = config.last_check_message
            else:
                # Belum ada record: pakai default model, tanpa membuat apa pun.
                values = Config.default_get(config_fields)
                settings.presenly_saas_last_check_at = False
                settings.presenly_saas_last_check_status = False
                settings.presenly_saas_last_check_message = False

            settings.presenly_saas_enabled = values.get('enabled', False)
            settings.presenly_saas_environment = values.get('environment', 'production')
            settings.presenly_saas_base_url = values.get('base_url', False)
            settings.presenly_saas_tenant_code = values.get('tenant_code', False)
            settings.presenly_saas_api_key = values.get('api_key', False)
            settings.presenly_saas_timeout_seconds = values.get('timeout_seconds', 10)
            settings.presenly_saas_retry_count = values.get('retry_count', 2)
            settings.presenly_saas_guard_mode = values.get('guard_mode', 'warn')
            settings.presenly_saas_grace_days = values.get('grace_days', 7)
            settings.presenly_saas_show_banner = values.get('show_banner', True)
            settings.presenly_saas_pull_months = values.get('pull_months', 2)
            settings.presenly_saas_retention_months = values.get('retention_months', 12)
            settings.presenly_saas_request_auto_refresh = values.get(
                'request_auto_refresh', True
            )
            settings.presenly_saas_cron_sync_minutes = values.get(
                'cron_sync_minutes', 15
            )

    def _write_presenly_saas_config(self, values):
        """Tulis field yang diberikan ke konfigurasi company pada baris ini.

        Dibatasi ke group Manajer. Untuk pengguna yang tidak berhak membaca
        `api_key`, nilai field itu kosong; tanpa batas ini, menyimpan halaman
        Settings akan menghapus kunci yang sedang dipakai.
        """
        if not self.env.user.has_group(MANAGER_GROUP):
            return

        Config = self.env['presenly.saas.config']
        for settings in self:
            config = settings._presenly_saas_config_ensured()
            if any(config[field] != value for field, value in values.items()):
                config.write(values)

    def _inverse_presenly_saas_enabled(self):
        self._write_presenly_saas_config({'enabled': self.presenly_saas_enabled})

    def _inverse_presenly_saas_environment(self):
        self._write_presenly_saas_config({'environment': self.presenly_saas_environment})

    def _inverse_presenly_saas_base_url(self):
        self._write_presenly_saas_config({'base_url': self.presenly_saas_base_url})

    def _inverse_presenly_saas_tenant_code(self):
        self._write_presenly_saas_config({'tenant_code': self.presenly_saas_tenant_code})

    def _inverse_presenly_saas_api_key(self):
        self._write_presenly_saas_config({'api_key': self.presenly_saas_api_key})

    def _inverse_presenly_saas_timeout_seconds(self):
        self._write_presenly_saas_config({'timeout_seconds': self.presenly_saas_timeout_seconds})

    def _inverse_presenly_saas_retry_count(self):
        self._write_presenly_saas_config({'retry_count': self.presenly_saas_retry_count})

    def _inverse_presenly_saas_pull_months(self):
        self._write_presenly_saas_config(
            {'pull_months': max(1, self.presenly_saas_pull_months or 1)}
        )

    def _inverse_presenly_saas_cron_sync_minutes(self):
        menit = max(0, self.presenly_saas_cron_sync_minutes or 0)
        self._write_presenly_saas_config({'cron_sync_minutes': menit})

        # Irama cron disimpan di record `ir.cron`, bukan di konfigurasi. Nilai 0
        # berarti cron-nya dimatikan: datanya masih segar saat halamannya dibuka,
        # tetapi tidak ada lagi yang menyegarkan data yang tidak pernah dilihat.
        cron = self.env.ref(
            'presenly_saas.ir_cron_presenly_saas_sync_recent', raise_if_not_found=False
        )
        if cron and self.env.user.has_group(MANAGER_GROUP):
            cron.sudo().write({
                'interval_number': max(1, menit),
                'interval_type': 'minutes',
                'active': menit > 0,
            })

    def _inverse_presenly_saas_request_auto_refresh(self):
        self._write_presenly_saas_config(
            {'request_auto_refresh': self.presenly_saas_request_auto_refresh}
        )

    def _inverse_presenly_saas_retention_months(self):
        self._write_presenly_saas_config(
            {'retention_months': max(0, self.presenly_saas_retention_months or 0)}
        )

    def _inverse_presenly_saas_guard_mode(self):
        self._write_presenly_saas_config({'guard_mode': self.presenly_saas_guard_mode})

    def _inverse_presenly_saas_grace_days(self):
        self._write_presenly_saas_config({'grace_days': self.presenly_saas_grace_days})

    def _inverse_presenly_saas_show_banner(self):
        self._write_presenly_saas_config({'show_banner': self.presenly_saas_show_banner})

    # ------------------------------------------------------------------
    # Aksi
    # ------------------------------------------------------------------
    def action_presenly_saas_test_connection(self):
        """Tombol Uji Koneksi di halaman Settings.

        Odoo menyimpan perubahan settings lebih dulu sebelum menjalankan tombol
        object (lihat `SettingsFormController.beforeExecuteActionButton`), jadi
        nilai yang baru diketik sudah tersimpan saat metode ini berjalan.
        """
        self.ensure_one()
        return self._presenly_saas_config_ensured().action_test_connection()

    def action_presenly_saas_refresh_subscription(self):
        self.ensure_one()
        return self._presenly_saas_config_ensured().action_refresh_subscription()

    def action_presenly_saas_open_subscription(self):
        return self.env['presenly.saas.subscription']._action_open_dashboard()
