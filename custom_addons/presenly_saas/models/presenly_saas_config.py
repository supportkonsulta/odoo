import logging
from calendar import monthrange
from datetime import date

from dateutil.relativedelta import relativedelta

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

# Pengajuan berperiode yang ikut ditarik bersama presensi. Setiap entri adalah
# (resource di API, model cermin). Semuanya punya kolom tanggal, jadi
# penarikannya mengganti per rentang, bukan mengganti seluruh isi.
# Cermin berperiode beserta kolom tanggalnya. Hanya model di daftar ini yang
# ikut dibersihkan oleh jendela bergulir. Cermin referensi (lokasi kerja, shift,
# mode absen, hari libur, setup hari kerja) tidak punya periode, jadi tidak
# pernah dihapus: isinya keadaan terkini, bukan riwayat.
PERIOD_MIRRORS = [
    ('presenly.saas.attendance.log', 'work_date'),
    ('presenly.saas.leave', 'leave_date'),
    ('presenly.saas.overtime', 'overtime_date'),
    ('presenly.saas.medical.certificate', 'certificate_date'),
    ('presenly.saas.attendance.correction', 'date'),
    ('presenly.saas.shift.swap', 'requester_date'),
    ('presenly.saas.timesheet', 'date'),
]

# Data berperiode yang ditarik bersama presensi, selain log dan rekap.
# Semuanya punya kolom tanggal, jadi penarikannya mengganti per rentang.
PERIOD_DATASETS = [
    ('leaves', 'presenly.saas.leave'),
    ('overtimes', 'presenly.saas.overtime'),
    ('medical-certificates', 'presenly.saas.medical.certificate'),
    ('attendance-corrections', 'presenly.saas.attendance.correction'),
    ('shift-swaps', 'presenly.saas.shift.swap'),
    ('timesheets', 'presenly.saas.timesheet'),
]

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
    ('projects', 'presenly.saas.project'),
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

    pull_months = fields.Integer(
        string='Months Pulled by Cron',
        default=2,
        help='How many months the daily pull covers, counting back from the '
             'current month. 2 means the current month and the one before it, '
             'so a shift that ends after midnight, or a correction filed the '
             'next day, is still captured.',
    )
    retention_months = fields.Integer(
        string='Retention (months)',
        default=12,
        help='Mirrored period data older than this is removed by the weekly '
             'cleanup. 0 keeps everything. Reference data is never removed: it '
             'has no period.',
    )

    _company_uniq = models.Constraint(
        'unique(company_id)',
        'Only one Presenly SaaS connection is allowed per company.',
    )
    _pull_months_at_least_one = models.Constraint(
        'CHECK(pull_months >= 1)',
        'At least one month must be pulled.',
    )
    _retention_not_negative = models.Constraint(
        'CHECK(retention_months >= 0)',
        'Retention cannot be negative.',
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
    def action_pull_reference_data(self):
        """Segarkan seluruh cermin data referensi."""
        self.ensure_one()
        self._ensure_manager()
        summary, error = self._pull_reference_data()
        if error:
            return self._notify('danger', _('Failed to pull reference data'), error)
        return self._notify(
            'success',
            _('Reference data updated'),
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
            'name': _('Pull Period Data'),
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

    def _crosscheck_attendance(self, month, year):
        """Bandingkan agregat cermin log dengan cermin rekap untuk bulan yang sama.

        Keduanya berasal dari server, tetapi dihitung oleh service yang berbeda.
        Kalau angkanya berbeda, salah satu tidak lengkap, dan itu harus terlihat
        bukan diam-diam dianggap benar.
        """
        self.ensure_one()
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])

        logs = self.env['presenly.saas.attendance.log'].search([
            ('company_id', '=', self.company_id.id),
            ('work_date', '>=', first_day),
            ('work_date', '<=', last_day),
        ])
        recap = self.env['presenly.saas.attendance.recap'].search([
            ('company_id', '=', self.company_id.id),
            ('month', '=', month),
            ('year', '=', year),
        ])

        def key_of(record):
            return record.employee_nopeg or 'id:%s' % record.user_id

        local = {}
        for log in logs:
            bucket = local.setdefault(key_of(log), [0, 0])
            bucket[0] += 1
            bucket[1] += log.late_minutes

        server = {
            key_of(row): [row.attendance_count, row.total_late_minutes]
            for row in recap
        }

        mismatches = []
        for key in sorted(set(local) | set(server)):
            local_pair = local.get(key, [0, 0])
            server_pair = server.get(key, [0, 0])
            if local_pair != server_pair:
                mismatches.append(_(
                    '%(key)s: the mirrored log has %(lcount)s sessions/'
                    '%(llate)s minutes, the server recap has %(scount)s sessions/'
                    '%(slate)s minutes',
                    key=key,
                    lcount=local_pair[0], llate=local_pair[1],
                    scount=server_pair[0], slate=server_pair[1],
                ))
        return mismatches

    def _pull_period_range(self, end_month, end_year, months_back=1):
        """Tarik beberapa bulan ke belakang, berakhir di bulan yang dipilih.

        Satu bulan berisi presensi (log + rekap) dan lima jenis pengajuan.
        Mengembalikan ``(summary, error)`` dengan total gabungan, daftar bulan
        yang terpotong, dan daftar ketidakcocokan uji silang.
        """
        self.ensure_one()
        self._require_enabled()

        months = max(1, int(months_back or 1))
        end = date(int(end_year), int(end_month), 1)

        total = {'logs': 0, 'recap': 0, 'months': 0, 'datasets': {}}
        truncated = []
        mismatches = []
        periods = []

        for offset in range(months - 1, -1, -1):
            current = end - relativedelta(months=offset)
            summary, error = self._pull_attendance(current.month, current.year)
            if error:
                return total, error
            total['logs'] += summary['logs']
            total['recap'] += summary['recap']
            truncated.extend(summary['truncated'])

            datasets, error = self._pull_period_datasets(current.month, current.year)
            if error:
                return total, error
            for resource, count in datasets['rows'].items():
                total['datasets'][resource] = total['datasets'].get(resource, 0) + count
            truncated.extend(datasets['truncated'])

            total['months'] += 1
            periods.append(summary['period'])
            mismatches.extend(self._crosscheck_attendance(current.month, current.year))

        total['periods'] = periods
        total['truncated'] = truncated
        total['mismatches'] = mismatches
        return total, False

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
                _('Attendance log: %(fetched)s of %(total)s rows fetched '
                  '(%(pages)s page limit).',
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

    def _pull_period_datasets(self, month, year):
        """Tarik pengajuan dan timesheet untuk satu bulan.

        Kalau satu jenis gagal, penarikan bulan itu berhenti dan galatnya
        dikembalikan. Jenis yang sudah tersimpan tetap tersimpan, dan yang
        belum tidak diklaim berhasil.
        """
        self.ensure_one()
        self._require_enabled()
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])

        summary = {
            'period': '%02d/%s' % (month, year),
            'rows': {},
            'truncated': [],
        }

        client = self._client()
        for resource, model_name in PERIOD_DATASETS:
            started = fields.Datetime.now()
            path = '/api/external/v1/%s' % resource
            params = {
                'since': fields.Date.to_string(first_day),
                'until': fields.Date.to_string(last_day),
                'limit': 500,
            }
            try:
                rows, meta, _pages = self._fetch_pages(
                    lambda page_params, _client=client, _resource=resource:
                        _client.get_resource(_resource, page_params),
                    params,
                )
            except SaasClientError as exc:
                error = redact(exc, self.api_key)
                self._log_pull(path, False, exc, started)
                return summary, error

            model = self.env[model_name]
            model._mirror_replace_range(self.company_id, rows, first_day, last_day)
            summary['rows'][resource] = len(rows)
            self._log_pull(path, True, None, started)

            total = int(meta.get('total') or 0)
            if total and len(rows) < total:
                summary['truncated'].append(
                    _('%(resource)s: %(fetched)s of %(total)s rows fetched '
                      '(%(pages)s page limit).',
                      resource=resource, fetched=len(rows), total=total,
                      pages=MAX_PULL_PAGES)
                )

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
    def _retention_cutoff(self):
        """Tanggal paling tua yang masih disimpan. False berarti simpan semua."""
        self.ensure_one()
        months = int(self.retention_months or 0)
        if months <= 0:
            return False
        return fields.Date.context_today(self) - relativedelta(months=months)

    def _prune_mirrors(self):
        """Hapus cermin berperiode yang lebih tua dari jendela bergulir.

        Mengembalikan jumlah baris yang dihapus per model, supaya pemanggilnya
        bisa melaporkan apa yang benar-benar terjadi, bukan sekadar "selesai".

        Cermin referensi tidak disentuh: isinya keadaan terkini, bukan riwayat,
        jadi menghapusnya berdasarkan umur justru menghilangkan data yang masih
        berlaku.
        """
        self.ensure_one()
        cutoff = self._retention_cutoff()
        if not cutoff:
            return {}

        removed = {}
        for model_name, date_field in PERIOD_MIRRORS:
            old_rows = self.env[model_name].sudo().search([
                ('company_id', '=', self.company_id.id),
                (date_field, '<', cutoff),
            ])
            if old_rows:
                removed[model_name] = len(old_rows)
                old_rows.unlink()

        # Rekap tidak punya kolom tanggal: periodenya adalah pasangan
        # (bulan, tahun). Dibandingkan sebagai nomor bulan berjalan supaya
        # Desember 2025 < Januari 2026.
        batas = cutoff.year * 12 + cutoff.month
        recap = self.env['presenly.saas.attendance.recap'].sudo().search([
            ('company_id', '=', self.company_id.id),
        ]).filtered(lambda row: row.year * 12 + row.month < batas)
        if recap:
            removed['presenly.saas.attendance.recap'] = len(recap)
            recap.unlink()

        return removed

    def _cron_pull_periods_all(self):
        """Tarik presensi dan pengajuan terbaru untuk setiap koneksi aktif.

        Terpisah dari cron langganan: langganan cukup diperiksa sekali sehari
        juga, tetapi kegagalannya tidak boleh menghentikan penarikan data, dan
        sebaliknya. Satu tenant yang gagal tidak pernah menghentikan tenant lain.
        """
        configs = self.sudo().search([('enabled', '=', True), ('active', '=', True)])
        today = fields.Date.context_today(self)
        for config in configs:
            months = max(1, int(config.pull_months or 1))
            try:
                _summary, error = config._pull_period_range(today.month, today.year, months)
            except UserError as exc:      # masalah konfigurasi, bukan galat jarak jauh
                error = str(exc)
            if error:
                _logger.warning(
                    "Presenly SaaS: period pull failed for company %s: %s",
                    config.company_id.display_name,
                    error,
                )
        self.env['presenly.saas.sync.log']._prune()
        return True

    @api.model
    def _cron_prune_mirrors_all(self):
        """Jalankan pembersihan jendela bergulir untuk setiap koneksi aktif."""
        configs = self.sudo().search([('enabled', '=', True), ('active', '=', True)])
        for config in configs:
            try:
                removed = config._prune_mirrors()
            except UserError as exc:
                _logger.warning(
                    "Presenly SaaS: mirror cleanup failed for company %s: %s",
                    config.company_id.display_name,
                    exc,
                )
                continue
            if removed:
                _logger.info(
                    "Presenly SaaS: removed %s mirrored rows for company %s",
                    sum(removed.values()),
                    config.company_id.display_name,
                )
        return True

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
