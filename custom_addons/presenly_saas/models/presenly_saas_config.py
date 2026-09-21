import logging
from calendar import monthrange
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.saas_client import PresenlySaasClient, SaasClientError, redact

_logger = logging.getLogger(__name__)

SUBSCRIPTION_PATH = "/api/external/v1/subscription"

# Endpoint fitur Presenly (bentuk bisnis, bukan mirror tabel).
# Kontrak: docs/external-presenly-api.md di repo backend_presenly.
FEATURES_PATH = "/api/external/v1/presenly/features"
ATTENDANCE_LOGS_PATH = "/api/external/v1/presenly/attendance-logs"
ATTENDANCE_RECAP_PATH = "/api/external/v1/presenly/attendance-recap"

# Batas halaman saat menarik daftar berhalaman. Bukan pengaman teknis, tapi
# pengaman operasional: satu tombol tidak boleh menarik ratusan ribu baris dan
# mengunci worker. Kalau batasnya tersentuh, itu diberitahukan ke pengguna.
MAX_PULL_PAGES = 10

# Cermin data referensi. Resource API -> model Odoo yang menyimpannya.
# Semuanya tanpa periode: penarikan mengganti seluruh isinya.
REFERENCE_MIRRORS = (
    ('work-locations', 'presenly.saas.work.location'),
    ('shifts', 'presenly.saas.shift'),
    ('attendance-modes', 'presenly.saas.attendance.mode'),
    ('holidays', 'presenly.saas.holiday'),
    ('work-day-setups', 'presenly.saas.work.day.setup'),
)

MANAGER_GROUP = 'presenly_saas.group_presenly_saas_manager'


class PresenlySaasConfig(models.Model):
    """Connection settings for one Presenly SaaS tenant.

    A single record per company, created on demand by :meth:`_get_or_create`.
    Nothing here extends ``res.config.settings`` or ``ir.config_parameter``:
    this module owns its own configuration screen.
    """

    _name = 'presenly.saas.config'
    _description = 'Presenly SaaS Connection'
    _rec_name = 'name'

    name = fields.Char(default='Presenly SaaS', required=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    active = fields.Boolean(default=True)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    enabled = fields.Boolean(
        string='Connection Enabled',
        default=False,
        help='When off, the module never calls the SaaS server and every '
             'subscription check is skipped.',
    )
    environment = fields.Selection(
        [('production', 'Production'), ('sandbox', 'Sandbox')],
        default='production',
        required=True,
        help='Label only. It is recorded so a sandbox connection is never '
             'mistaken for a production one during support.',
    )
    base_url = fields.Char(
        string='Base URL',
        help='Origin of the Presenly SaaS server, for example '
             'https://presensi.konsultasg.com. The /api suffix is optional.',
    )
    tenant_code = fields.Char(
        string='Tenant Code',
        help='Tenant identifier on the SaaS side, sent as the X-Tenant-ID '
             'header. Example: pelni.',
    )
    api_key = fields.Char(
        string='API Key',
        groups=MANAGER_GROUP,
        help='Sent as the X-API-Key header. Only managers can read or change it.',
    )
    timeout_seconds = fields.Integer(string='Timeout (seconds)', default=10)
    retry_count = fields.Integer(
        string='Retries',
        default=2,
        help='Retries on network errors and 5xx responses. Authentication '
             'failures are never retried.',
    )

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------
    guard_mode = fields.Selection(
        [
            ('off', 'Off'),
            ('warn', 'Warn only'),
            ('enforce', 'Enforce'),
        ],
        default='warn',
        required=True,
        help='Off: status is visible on the dashboard only.\n'
             'Warn only: the dashboard plus a warning banner in the backend.\n'
             'Enforce: the banner plus presenly.saas.guard.check() raising for '
             'the modules that call it.',
    )
    grace_days = fields.Integer(
        string='Grace Period (days)',
        default=7,
        help='How long a cached status stays acceptable after the last '
             'successful sync. A network failure never blocks on its own.',
    )
    show_banner = fields.Boolean(
        string='Show Banner',
        default=True,
        help='Display the subscription banner in the backend when the status '
             'needs attention.',
    )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    last_check_at = fields.Datetime(string='Last Check', readonly=True)
    last_check_status = fields.Selection(
        [('success', 'Success'), ('failed', 'Failed')],
        string='Last Check Status',
        readonly=True,
    )
    last_check_message = fields.Text(string='Last Check Result', readonly=True)

    _company_uniq = models.Constraint(
        'unique(company_id)',
        'Only one Presenly SaaS connection is allowed per company.',
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_or_create(self, company=None):
        """Return the singleton connection record for ``company``."""
        company = company or self.env.company
        config = self.sudo().search([('company_id', '=', company.id)], limit=1)
        if not config:
            config = self.sudo().create({
                'company_id': company.id,
                'name': _('Presenly SaaS'),
            })
        return config

    @api.model
    def _action_open_connection(self):
        """Open the singleton connection form from a menu entry."""
        config = self._get_or_create()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Presenly SaaS Connection'),
            'res_model': self._name,
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _ensure_manager(self):
        if not self.env.user.has_group(MANAGER_GROUP):
            raise UserError(_("Only Presenly SaaS managers can perform this action."))

    @api.constrains('base_url')
    def _check_base_url(self):
        for config in self:
            url = (config.base_url or '').strip()
            if url and not url.startswith(('http://', 'https://')):
                raise UserError(
                    _("Base URL must start with http:// or https:// (got %s).", url)
                )

    @api.constrains('timeout_seconds', 'retry_count', 'grace_days')
    def _check_positive_numbers(self):
        for config in self:
            if config.timeout_seconds <= 0:
                raise UserError(_("Timeout must be greater than zero."))
            if config.retry_count < 0:
                raise UserError(_("Retries cannot be negative."))
            if config.grace_days < 0:
                raise UserError(_("Grace period cannot be negative."))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_test_connection(self):
        """Call the subscription endpoint and report the result in the form."""
        self.ensure_one()
        self._ensure_manager()
        _subscription, error = self._fetch_and_store(log=False)
        if error:
            return self._notify('danger', _('Connection failed'), error)
        return self._notify(
            'success',
            _('Connection ok'),
            self.last_check_message or _('The Presenly SaaS server answered.'),
        )

    def action_refresh_subscription(self):
        """Call the subscription endpoint and update the local snapshot."""
        self.ensure_one()
        self._ensure_manager()
        _subscription, error = self._fetch_and_store(log=True)
        if error:
            return self._notify('danger', _('Refresh failed'), error)
        return self._notify(
            'success',
            _('Subscription refreshed'),
            self.last_check_message or _('The subscription snapshot is up to date.'),
        )

    def _fetch_and_store(self, log):
        """Fetch the subscription, write the snapshot, and return the outcome.

        Returns ``(subscription, error_message)``. A remote failure is returned
        as a value instead of being raised on purpose: an exception reaching the
        RPC layer makes Odoo roll the transaction back, which would throw away
        the diagnostics written just before it.
        """
        self.ensure_one()
        started = fields.Datetime.now()
        try:
            data = self._fetch_subscription()
        except SaasClientError as exc:
            error = redact(exc, self.api_key)
            self._write_check_result(False, error)
            self.env['presenly.saas.subscription']._mark_unreachable(self.company_id)
            if log:
                self.env['presenly.saas.sync.log']._record(
                    self.company_id,
                    SUBSCRIPTION_PATH,
                    success=False,
                    http_status=exc.http_status,
                    duration_ms=self._elapsed_ms(started),
                    error_message=error,
                )
            return self.env['presenly.saas.subscription'], error

        subscription = self.env['presenly.saas.subscription']._sync_from_payload(self, data)
        summary = self._format_summary(subscription)
        self._write_check_result(True, summary)
        if log:
            self.env['presenly.saas.sync.log']._record(
                self.company_id,
                SUBSCRIPTION_PATH,
                success=True,
                http_status=200,
                duration_ms=self._elapsed_ms(started),
            )
        return subscription, False

    # ------------------------------------------------------------------
    # Aksi tarik data (dipakai dari menu)
    # ------------------------------------------------------------------
    def action_pull_external_features(self):
        """Segarkan katalog fitur eksternal."""
        self.ensure_one()
        self._ensure_manager()
        features, error = self._pull_features()
        if error:
            return self._notify('danger', _('Gagal menarik katalog fitur'), error)
        return self._notify(
            'success',
            _('Katalog fitur diperbarui'),
            _('%(count)s fitur, %(available)s tersedia.',
              count=len(features),
              available=len(features.filtered(lambda f: f.status == 'available'))),
        )

    def action_pull_reference_data(self):
        """Segarkan seluruh cermin data referensi."""
        self.ensure_one()
        self._ensure_manager()
        summary, error = self._pull_reference_data()
        if error:
            return self._notify('danger', _('Gagal menarik data referensi'), error)
        return self._notify(
            'success',
            _('Data referensi diperbarui'),
            '\n'.join(
                '%s: %s' % (resource, count)
                for resource, count in sorted(summary.items())
            ),
        )

    def action_open_pull_wizard(self):
        """Buka pemilih periode sebelum menarik presensi."""
        self.ensure_one()
        self._ensure_manager()
        today = fields.Date.context_today(self)
        wizard = self.env['presenly.saas.pull.wizard'].create({
            'config_id': self.id,
            'month': str(today.month),
            'year': today.year,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tarik Data Presensi'),
            'res_model': 'presenly.saas.pull.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Penarikan data fitur Presenly (/v1/presenly/*)
    # ------------------------------------------------------------------
    def _client(self):
        self.ensure_one()
        if not (self.base_url and self.tenant_code and self.api_key):
            raise UserError(
                _("Base URL, Tenant Code and API Key must be filled in before "
                  "contacting the Presenly SaaS server.")
            )
        return PresenlySaasClient(
            base_url=self.base_url,
            api_key=self.api_key,
            tenant_code=self.tenant_code,
            timeout=self.timeout_seconds or 10,
            retry_count=self.retry_count,
        )

    def _pull_features(self):
        """Tarik katalog fitur eksternal. Mengembalikan ``(features, error)``.

        Kegagalan dikembalikan sebagai nilai, bukan dilempar, dengan alasan yang
        sama seperti `_fetch_and_store`: exception yang naik ke layer RPC membuat
        Odoo me-rollback transaksi, sehingga catatan audit yang baru ditulis ikut
        hilang.
        """
        self.ensure_one()
        self._require_enabled()
        started = fields.Datetime.now()
        try:
            envelope = self._client().get_presenly_features()
        except SaasClientError as exc:
            error = redact(exc, self.api_key)
            self._log_pull(FEATURES_PATH, False, exc, started)
            return self.env['presenly.saas.external.feature'], error

        features = self.env['presenly.saas.external.feature']._sync_from_payload(
            self, envelope.get('data') or []
        )
        self._log_pull(FEATURES_PATH, True, None, started)
        return features, False

    def _pull_reference_data(self):
        """Tarik seluruh resource referensi. Mengembalikan ``(summary, error)``."""
        self.ensure_one()
        self._require_enabled()
        client = self._client()
        summary = {}

        for resource, model_name in REFERENCE_MIRRORS:
            started = fields.Datetime.now()
            try:
                rows, _meta, _pages = self._fetch_pages(
                    # Default arg mengikat `resource` per iterasi.
                    lambda params, r=resource: client.get_resource(r, params),
                    {'limit': 500},
                )
            except SaasClientError as exc:
                error = redact(exc, self.api_key)
                self._log_pull('/v1/%s' % resource, False, exc, started)
                return summary, error

            summary[resource] = self.env[model_name]._mirror_replace(
                self.company_id, rows
            )
            self._log_pull('/v1/%s' % resource, True, None, started)

        return summary, False

    def _pull_attendance(self, month, year):
        """Tarik log dan rekap presensi untuk satu bulan.

        Mengembalikan ringkasan berisi jumlah baris per dataset, dan catatan
        bila penarikan berhenti karena batas halaman. Cermin yang tidak lengkap
        tidak boleh tampak seperti data yang lengkap.
        """
        self.ensure_one()
        self._require_enabled()
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])

        summary = {'period': '%02d/%s' % (month, year), 'logs': 0, 'recap': 0, 'truncated': []}

        # --- Log presensi: berhalaman, diganti per rentang tanggal ---
        started = fields.Datetime.now()
        try:
            rows, meta, _pages = self._fetch_pages(
                self._client().get_attendance_logs,
                {
                    'start_date': fields.Date.to_string(first_day),
                    'end_date': fields.Date.to_string(last_day),
                    'limit': 500,
                },
            )
        except SaasClientError as exc:
            error = redact(exc, self.api_key)
            self._log_pull(ATTENDANCE_LOGS_PATH, False, exc, started)
            return summary, error

        log_model = self.env['presenly.saas.attendance.log']
        log_model._replace_scope(self.company_id, first_day, last_day)
        summary['logs'] = log_model._upsert_rows(self.company_id, rows)
        self._log_pull(ATTENDANCE_LOGS_PATH, True, None, started)

        total = int(meta.get('total') or 0)
        if total and len(rows) < total:
            summary['truncated'].append(
                _('Log presensi: %(fetched)s dari %(total)s baris terambil '
                  '(batas %(pages)s halaman).',
                  fetched=len(rows), total=total, pages=MAX_PULL_PAGES)
            )

        # --- Rekap: satu halaman, diganti per bulan ---
        started = fields.Datetime.now()
        try:
            envelope = self._client().get_attendance_recap({'month': month, 'year': year})
        except SaasClientError as exc:
            # Log presensi sudah tersimpan; hanya rekapnya yang gagal. Itu
            # dilaporkan apa adanya, bukan dianggap gagal total.
            error = redact(exc, self.api_key)
            self._log_pull(ATTENDANCE_RECAP_PATH, False, exc, started)
            return summary, error

        recap_model = self.env['presenly.saas.attendance.recap']
        recap_model._replace_scope(self.company_id, month, year)
        summary['recap'] = recap_model._upsert_rows(self.company_id, envelope.get('data') or [])
        self._log_pull(ATTENDANCE_RECAP_PATH, True, None, started)

        return summary, False

    def _fetch_pages(self, method, params, max_pages=MAX_PULL_PAGES):
        """Ambil halaman demi halaman sampai habis atau batas tercapai."""
        rows = []
        meta = {}
        page = 1
        while page <= max_pages:
            envelope = method(dict(params or {}, page=page))
            rows.extend(envelope.get('data') or [])
            meta = envelope.get('meta') or {}
            total_pages = int(meta.get('total_pages') or 0)
            if not total_pages or page >= total_pages:
                break
            page += 1
        return rows, meta, page

    def _require_enabled(self):
        self.ensure_one()
        if not self.enabled:
            raise UserError(_("The Presenly SaaS connection is disabled."))

    def _log_pull(self, endpoint, success, exc, started):
        self.env['presenly.saas.sync.log']._record(
            self.company_id,
            endpoint,
            success=success,
            http_status=getattr(exc, 'http_status', None) or (200 if success else 0),
            duration_ms=self._elapsed_ms(started),
            error_message=redact(exc, self.api_key) if exc else None,
        )

    def _fetch_subscription(self):
        self.ensure_one()
        if not self.enabled:
            raise UserError(_("The Presenly SaaS connection is disabled."))
        if not (self.base_url and self.tenant_code and self.api_key):
            raise UserError(
                _("Base URL, Tenant Code and API Key must be filled in before "
                  "contacting the Presenly SaaS server.")
            )
        client = PresenlySaasClient(
            base_url=self.base_url,
            api_key=self.api_key,
            tenant_code=self.tenant_code,
            timeout=self.timeout_seconds or 10,
            retry_count=self.retry_count,
        )
        return client.get_subscription()

    def _write_check_result(self, success, message):
        self.sudo().write({
            'last_check_at': fields.Datetime.now(),
            'last_check_status': 'success' if success else 'failed',
            'last_check_message': message,
        })

    @staticmethod
    def _elapsed_ms(started):
        return int((fields.Datetime.now() - started).total_seconds() * 1000)

    def _format_summary(self, subscription):
        translate = self.env._
        parts = [translate("Plan: %s", subscription.plan_type or '-')]
        parts.append(translate("Status: %s", subscription._status_label()))
        # Trials carry `trial_ends_at` while paid periods carry
        # `current_period_end`; the summary must show whichever applies, or a
        # trial looks like it never ends.
        end = subscription._validity_end()
        if end:
            parts.append(translate("Valid until: %s", fields.Datetime.to_string(end)))
        if subscription.seat_limit:
            parts.append(
                translate(
                    "Seats: %(used)s of %(limit)s",
                    used=subscription.seats_used,
                    limit=subscription.seat_limit,
                )
            )
        return "\n".join(parts)

    @staticmethod
    def _notify(notification_type, title, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': notification_type,
                'title': title,
                'message': message,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_refresh_all(self):
        """Refresh every enabled connection. Never raises for one tenant."""
        configs = self.sudo().search([('enabled', '=', True), ('active', '=', True)])
        for config in configs:
            try:
                _subscription, error = config._fetch_and_store(log=True)
            except UserError as exc:  # configuration problem, not a remote failure
                error = str(exc)
            if error:
                _logger.warning(
                    "Presenly SaaS: refresh failed for company %s: %s",
                    config.company_id.display_name,
                    error,
                )
        self.env['presenly.saas.sync.log']._prune()
        return True
