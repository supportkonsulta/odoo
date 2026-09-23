import logging
import secrets

from odoo import _, api, fields, models

from odoo.addons.presenly_saas.models.presenly_saas_config import MANAGER_GROUP, redact
from odoo.addons.presenly_saas.services.saas_client import SaasClientError

_logger = logging.getLogger(__name__)

# Kontrak: docs/external-webhooks.md di repo backend_presenly.
WEBHOOKS_PATH = "/api/external/v1/webhooks"
EMPLOYEES_PATH = "/api/external/v1/employees"


class PresenlySaasConfig(models.Model):
    """Bagian integrasi pegawai pada konfigurasi Presenly.

    Ada di modul terpisah supaya `presenly_saas` tidak memaksa pemasangan `hr`
    beserta `resource`, `mail`, dan `phone_validation` yang ikut terbawa.
    """

    _inherit = 'presenly.saas.config'

    webhook_enabled = fields.Boolean(
        string='Send Change Notifications',
        default=False,
        help='Register this Odoo with the Presenly server so it is told when an '
             'employee changes there, instead of waiting for the next pull.',
    )
    webhook_url = fields.Char(
        string='Webhook URL',
        readonly=True,
        copy=False,
        help='This Odoo\'s receiving address, registered on the Presenly server.',
    )
    webhook_secret = fields.Char(
        string='Webhook Secret',
        readonly=True,
        copy=False,
        groups=MANAGER_GROUP,
        help='HMAC key used to verify incoming calls. Created by the Presenly '
             'server and shown only through the registration call.',
    )
    webhook_token = fields.Char(
        string='Webhook Token',
        readonly=True,
        copy=False,
        default=lambda self: secrets.token_urlsafe(32),
        help='Random part of the receiving URL. Without it, anyone who guesses the '
             'path could trigger a sync.',
    )
    webhook_last_received_at = fields.Datetime(
        string='Last Notification Received',
        readonly=True,
        copy=False,
    )

    def _pull_employees(self):
        """Tarik pegawai ke cermin, lalu terapkan ke `hr.employee`.

        Satu arah: Presenly -> Odoo. Arah sebaliknya menunggu endpoint tulis di
        sisi server, jadi metode ini **tidak** dipasang di cron: selama arah
        baliknya belum ada, sinkronisasi terjadwal akan menimpa perubahan yang
        dilakukan di Odoo tanpa pemberitahuan.

        Mengembalikan ``(summary, error)``.
        """
        self.ensure_one()
        self._require_enabled()
        started = fields.Datetime.now()

        client = self._client()
        try:
            rows, _meta, _pages = self._fetch_pages(
                # `get_resource` mengambil nama resource sebagai argumen pertama,
                # sedangkan `_fetch_pages` hanya meneruskan satu argumen.
                lambda params: client.get_resource('employees', params),
                {'limit': 500},
            )
        except SaasClientError as exc:
            error = redact(exc, self.api_key)
            self._log_pull(EMPLOYEES_PATH, False, exc, started)
            return {}, error

        mirror = self.env['presenly.saas.employee']
        pulled = mirror._upsert_rows(self.company_id, rows)
        self._log_pull(EMPLOYEES_PATH, True, None, started)

        summary = mirror._sync_to_hr(self.company_id)
        summary['pulled'] = pulled

        # Kirim balik setelah menarik, dan hanya untuk kolom yang berubah di
        # Odoo SETELAH tarikan ini. Urutannya penting: kalau dikirim lebih dulu,
        # nilai lama Odoo akan menimpa nilai baru dari Presenly.
        started = fields.Datetime.now()
        try:
            pushed = mirror._push_to_presenly(self.company_id, client)
        except SaasClientError as exc:
            self._log_pull(EMPLOYEES_PATH, False, exc, started)
            return summary, redact(exc, self.api_key)
        self._log_pull(EMPLOYEES_PATH, True, None, started)
        summary['push'] = pushed

        return summary, False

    @api.model
    def _find_by_webhook_token(self, token):
        """Cari koneksi dari token di alamat webhook.

        Diletakkan di model, bukan di controller, supaya bisa diuji tanpa
        permintaan HTTP — dan supaya syaratnya (token cocok, webhook aktif,
        koneksi aktif) terbaca sebagai satu tempat.
        """
        if not token:
            return self.browse()
        return self.sudo().search([
            ('webhook_token', '=', token),
            ('webhook_enabled', '=', True),
            ('enabled', '=', True),
        ], limit=1)

    def _webhook_base_url(self):
        """Alamat yang bisa dijangkau server Presenly, bukan localhost."""
        self.ensure_one()
        return (self.env['ir.config_parameter'].sudo()
                .get_param('web.base.url') or '').rstrip('/')

    def _webhook_callback_url(self):
        self.ensure_one()
        if not self.webhook_token:
            self.sudo().webhook_token = secrets.token_urlsafe(32)
        return '%s/presenly_saas/webhook/%s' % (self._webhook_base_url(), self.webhook_token)

    def action_register_webhook(self):
        """Daftarkan alamat penerima instalasi ini ke server Presenly."""
        self.ensure_one()
        self._ensure_manager()
        self._require_enabled()

        url = self._webhook_callback_url()
        if not self._webhook_base_url():
            return self._notify(
                'danger',
                _('Webhook not registered'),
                _('The `web.base.url` system parameter is empty, so Presenly has no '
                  'address to call. Set it in Settings first.'),
            )

        try:
            hasil = self._client().register_webhook({
                'url': url,
                'events': [
                    'employee.created', 'employee.updated',
                    # Klien dan lokasi kerja membentuk perusahaan serta
                    # `hr.work.location` di sisi ini.
                    'client.created', 'client.updated',
                    'work_location.created', 'work_location.updated',
                ],
                'label': '%s (%s)' % (self.env.cr.dbname, self.tenant_code or 'no tenant'),
            })
        except SaasClientError as exc:
            self._log_pull(WEBHOOKS_PATH, False, exc, fields.Datetime.now())
            return self._notify(
                'danger', _('Webhook not registered'), redact(exc, self.api_key),
            )

        data = hasil.get('data') or {}
        self.sudo().write({
            'webhook_url': data.get('url') or url,
            'webhook_secret': data.get('secret') or False,
            'webhook_enabled': True,
        })
        self._log_pull(WEBHOOKS_PATH, True, None, fields.Datetime.now())
        return self._notify(
            'success',
            _('Webhook registered'),
            _('Presenly will call %(url)s when an employee changes there.', url=url),
        )

    def action_unregister_webhook(self):
        """Hentikan pemberitahuan perubahan dari server Presenly."""
        self.ensure_one()
        self._ensure_manager()
        try:
            self._client().unregister_webhook()
        except SaasClientError as exc:
            self._log_pull(WEBHOOKS_PATH, False, exc, fields.Datetime.now())
            return self._notify(
                'danger', _('Webhook not disabled'), redact(exc, self.api_key),
            )
        self.sudo().write({'webhook_enabled': False})
        self._log_pull(WEBHOOKS_PATH, True, None, fields.Datetime.now())
        return self._notify(
            'success',
            _('Webhook disabled'),
            _('Presenly will no longer call this Odoo. Changes are picked up by the '
              'scheduled pull again.'),
        )

    def action_pull_employees(self):
        """Tombol: tarik pegawai dan laporkan hasilnya apa adanya."""
        self.ensure_one()
        self._ensure_manager()
        summary, error = self._pull_employees()
        if error:
            return self._notify(
                'danger', _('Failed to pull employees'), error,
            )

        push = summary.get('push') or {}
        message = _(
            "%(pulled)s employees pulled: %(created)s created, %(updated)s updated, "
            "%(unchanged)s unchanged. Sent back to Presenly: %(pushed)s.",
            pulled=summary['pulled'], created=summary['created'],
            updated=summary['updated'], unchanged=summary['unchanged'],
            pushed=push.get('pushed', 0),
        )
        notices = []
        if push.get('fields'):
            notices.append(
                _("Fields sent: %s", ', '.join(push['fields']))
            )
        if push.get('failed'):
            notices.append(
                _("Send failed:\n%s", '\n'.join(push['failed'][:10]))
            )
        if summary['conflicts']:
            notices.append(
                _("Changed in both systems:\n%s", '\n'.join(summary['conflicts'][:10]))
            )
        if summary['skipped']:
            notices.append(
                _("Skipped:\n%s", '\n'.join(summary['skipped'][:10]))
            )
        if summary['refused']:
            notices.append(
                _("Needs a decision in Odoo:\n%s", '\n'.join(summary['refused'][:10]))
            )
        if notices:
            message = '%s\n\n%s' % (message, '\n'.join(notices))
        return self._notify(
            'warning' if notices else 'success',
            _('Employee pull finished'),
            message,
        )

    def _cron_sync_employees_all(self):
        """Sinkronkan pegawai dua arah untuk setiap koneksi aktif.

        Bentrok dilaporkan ke log Odoo, bukan dilempar: cron tidak punya tempat
        untuk menampilkan notifikasi, dan satu tenant yang bermasalah tidak boleh
        menghentikan tenant lain.
        """
        configs = self.sudo().search([('enabled', '=', True), ('active', '=', True)])
        for config in configs:
            try:
                summary, error = config._pull_employees()
            except UserError as exc:
                error = str(exc)
                summary = {}
            if error:
                _logger.warning(
                    "Presenly SaaS: employee sync failed for company %s: %s",
                    config.company_id.display_name,
                    error,
                )
                continue
            if summary.get('conflicts'):
                _logger.warning(
                    "Presenly SaaS: %s employee(s) changed in both systems for "
                    "company %s; the Presenly value was kept.",
                    len(summary['conflicts']),
                    config.company_id.display_name,
                )
            push = summary.get('push') or {}
            if push.get('failed'):
                _logger.warning(
                    "Presenly SaaS: %s employee change(s) could not be sent back "
                    "for company %s.",
                    len(push['failed']),
                    config.company_id.display_name,
                )
        return True
