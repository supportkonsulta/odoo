import logging
from calendar import monthrange
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError

from .presenly_saas_attachment import ATTACHMENT_FIELDS
from .presenly_saas_attendance_log import parse_datetime
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

# Jenis pengajuan yang ditarik tambahan. Sengaja tanpa presensi, rekap, dan
# timesheet: tabel pengajuan kecil, sedangkan penarikan rentang presensi menulis
# ulang seluruh rentangnya setiap kali — menjalankannya tiap 15 menit berarti
# menulis ulang ribuan baris tiap 15 menit.
REQUEST_DATASETS = tuple(
    entry for entry in PERIOD_DATASETS if entry[0] != 'timesheets'
)

# Yang ditarik tambahan, dengan penanda waktunya sendiri-sendiri. Semuanya
# mendukung `updated_since` di sisi API: hanya baris yang berubah yang terambil,
# jadi menjalankannya sesering ini tidak berarti menulis ulang seluruh rentang.
#
# Item: (kunci penanda, path API, model cermin).
#
# Path-nya relatif ke akar API: klien HTTP sudah menambahkan `/api/external`
# sendiri. Yang dicatat ke log sinkronisasi adalah bentuk lengkapnya, supaya
# sebaris dengan catatan penarikan periode.
RECENT_DATASETS = tuple(
    (resource, '/v1/%s' % resource, model_name)
    for resource, model_name in PERIOD_DATASETS
    if resource != 'attendance-recap'
) + (
    # Endpoint presensi berbentuk halaman, bukan resource, tetapi bisa disaring
    # dengan `updated_since` yang sama.
    ('attendance-logs', '/v1/presenly/attendance-logs',
     'presenly.saas.attendance.log'),
)

# Cermin referensi jarang berubah, tetapi juga tidak pernah ikut penarikan
# harian: sebelumnya hanya bisa ditarik dengan tombol. Sekarang ikut disegarkan
# saat halamannya dibuka, paling sering sekali sejam.
REFERENCE_REFRESH_MINUTES = 60

# Batas waktu untuk penarikan yang dipicu dari halaman pengguna. Bawaannya 10
# detik terlalu lama untuk sebuah halaman daftar, dan percobaan ulang tidak
# dipakai di jalur ini: satu kegagalan harus terlihat sebagai daftar yang tidak
# bertambah, bukan sebagai halaman yang menggantung.
INLINE_PULL_TIMEOUT = 3

# Tumpang tindih saat meminta `updated_since`. API menyaring dengan
# `updated_at > since`, jadi baris yang berubah pada detik yang sama dengan
# penanda terakhir bisa terlewat.
INCREMENTAL_OVERLAP_MINUTES = 5

# Kunci penasihat untuk penarikan pengajuan dari halaman. Satu angka untuk seluruh
# modul: yang dijaga adalah "jangan ada dua penarikan berjalan bersamaan", bukan
# per perusahaan — penarikan per perusahaan sudah dipisah oleh datanya sendiri.
_REQUEST_LOCK_KEY = 0x70726573  # 'pres' dalam heksadesimal

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
    request_auto_refresh = fields.Boolean(
        string='Refresh on Open',
        default=True,
        help='When a mirror list is opened, ask the Presenly server in one cheap '
             'request whether anything changed, and pull only what did. Off means '
             'data is only refreshed by the scheduled pull.',
    )
    sync_companies = fields.Boolean(
        string='Create Companies from Clients',
        default=False,
        help='Create an Odoo company for each Presenly client, and keep its name, '
             'email, and phone in step. Off by default: a company is an accounting '
             'entity, so creating one is a decision, not a side effect. Companies '
             'are never deleted automatically.',
    )
    request_attachments = fields.Boolean(
        string='Pull Attachments',
        default=False,
        help='Download the files attached to requests (leave dispensation, '
             'medical certificate, timesheet photo) so they can be viewed in '
             'Odoo. The files are always personal, so this is off by default.',
    )
    cron_sync_minutes = fields.Integer(
        string='Scheduled Refresh (minutes)',
        default=15,
        help='How often the scheduled pull of recent data runs. 0 turns that cron '
             'off: data is still refreshed when its list is opened, but nothing '
             'keeps data nobody looks at up to date.',
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
    def _client(self, timeout=None, retry_count=None):
        """Klien HTTP untuk koneksi ini.

        `timeout` dan `retry_count` bisa ditimpa untuk jalur yang tidak boleh
        menunggu lama, yaitu penarikan yang dipicu dari halaman pengguna.
        """
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
            timeout=timeout or self.timeout_seconds or 10,
            retry_count=self.retry_count if retry_count is None else retry_count,
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
                self._log_pull('/api/external/v1/%s' % resource, False, exc, started)
                return summary, error

            summary[resource] = self.env[model_name]._mirror_replace(
                self.company_id, rows
            )
            self._log_pull('/api/external/v1/%s' % resource, True, None, started)

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
            if self.request_attachments and model_name in ATTACHMENT_FIELDS:
                # Jalur berkasnya kolom PII, jadi hanya ikut terkirim kalau diminta.
                params['include_pii'] = 'true'
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
            jumlah = len(rows)
            if self.request_attachments and model_name in ATTACHMENT_FIELDS:
                # Penarikan rentang mengganti barisnya, jadi lampirannya perlu
                # dipasang ulang. Isi berkasnya sendiri diambil dari cache.
                jumlah += self.env['presenly.saas.attachment.sync'].sync_attachments(
                    self.company_id, model_name, rows,
                    lambda satu_path: client.download_file(satu_path),
                )
            summary['rows'][resource] = jumlah
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

    def _pull_recent_data(self, datasets=None, client=None, timeout=None,
                          retry_count=None):
        """Tarik semua yang berubah sejak penarikan tambahan terakhir.

        Mencakup pengajuan, timesheet, dan log presensi — semuanya lewat
        `updated_since`, jadi yang dibandingkan adalah waktu perubahan di sisi
        server, bukan tanggal bisnis datanya. Rekap ikut disegarkan karena
        dihitung server per bulan dan isinya kecil. Cermin referensi ikut kalau
        sudah lama, karena isinya jarang berubah tetapi tidak pernah ikut
        penarikan harian.

        Mengembalikan ``(summary, error)``. Penanda waktu hanya dimajukan untuk
        jenis yang benar-benar berhasil: kegagalan dikembalikan sebagai nilai,
        jadi jenis yang gagal tidak boleh ikut maju — kalau ikut, perubahannya
        terlewat selamanya.
        """
        self.ensure_one()
        self._require_enabled()
        Mark = self.env['presenly.saas.sync.mark'].sudo()
        client = client or self._client(timeout=timeout, retry_count=retry_count)

        diminta = set(datasets) if datasets else None
        summary = {'datasets': {}, 'server_time': None, 'recap': 0,
                   'references': 0, 'clients': {}}
        for kunci, path, model_name in RECENT_DATASETS:
            if diminta is not None and kunci not in diminta:
                continue
            started = fields.Datetime.now()
            params = {'limit': 500}
            if self.request_attachments and model_name in ATTACHMENT_FIELDS:
                # Jalur berkasnya termasuk kolom PII, jadi hanya ikut terkirim
                # kalau diminta.
                params['include_pii'] = 'true'

            since = Mark._since(self.company_id, kunci, INCREMENTAL_OVERLAP_MINUTES)
            if since:
                # Odoo menyimpan waktu dalam UTC, dan API meminta ISO-8601.
                params['updated_since'] = since.strftime('%Y-%m-%dT%H:%M:%SZ')

            try:
                rows, meta, _pages = self._fetch_pages(
                    lambda page_params, _client=client, _path=path:
                        _client.get_envelope(_path, page_params),
                    params,
                )
            except SaasClientError as exc:
                self._log_pull('/api/external' + path, False, exc, started)
                return summary, redact(exc, self.api_key)

            if model_name == 'presenly.saas.attendance.log':
                # Cermin presensi punya penulisan tambah-perbarui sendiri.
                ditulis = self.env[model_name]._upsert_rows(self.company_id, rows)
            else:
                ditulis = self.env[model_name]._mirror_upsert(self.company_id, rows)
            if self.request_attachments and model_name in ATTACHMENT_FIELDS:
                ditulis += self.env['presenly.saas.attachment.sync'].sync_attachments(
                    self.company_id, model_name, rows,
                    lambda satu_path: client.download_file(satu_path),
                )
            summary['datasets'][kunci] = ditulis
            self._log_pull('/api/external' + path, True, None, started)

            # Waktu server, bukan jam Odoo: yang dibandingkan adalah `updated_at`
            # milik server, dan dua jam yang berbeda tidak boleh diadu.
            server_time = parse_datetime(meta.get('server_time')) or fields.Datetime.now()
            Mark._advance(self.company_id, kunci, server_time)
            summary['server_time'] = server_time

        # Rekap: dihitung server per bulan, isinya beberapa baris per pegawai.
        # Mengganti satu bulan lebih murah daripada menyimpannya basi.
        #
        # Tidak ikut diperiksa `changes` — rekap dihitung server, bukan tabel —
        # jadi ia ikut ditarik ketika ada yang berubah, atau ketika penarikan ini
        # memang menarik semuanya (cron dan penarikan periode).
        if diminta is not None and not diminta:
            return summary, False
        today = fields.Date.context_today(self)
        started = fields.Datetime.now()
        path = ATTENDANCE_RECAP_PATH
        try:
            envelope = client.get_attendance_recap({'month': today.month, 'year': today.year})
        except SaasClientError as exc:
            self._log_pull(path, False, exc, started)
            return summary, redact(exc, self.api_key)
        Recap = self.env['presenly.saas.attendance.recap']
        Recap._replace_scope(self.company_id, today.month, today.year)
        summary['recap'] = Recap._upsert_rows(self.company_id, envelope.get('data') or [])
        self._log_pull(path, True, None, started)

        # Klien: menjadi perusahaan Odoo, kalau memang diizinkan. Dilakukan
        # sebelum referensi supaya lokasi kerja punya perusahaan tujuan.
        if self.sync_companies:
            ringkas_klien, error_klien = self._pull_clients()
            summary['clients'] = ringkas_klien
            if error_klien:
                return summary, error_klien

        # Referensi: seluruh isinya diganti, dan tabelnya kecil.
        if self._references_need_refresh():
            ringkas, error = self._pull_reference_data()
            if error:
                return summary, error
            summary['references'] = len(ringkas)

        return summary, False

    def _references_need_refresh(self):
        """Apakah cermin referensi sudah cukup tua untuk disegarkan lagi."""
        self.ensure_one()
        sejak = self._seconds_since_attempt(self._reference_paths())
        return sejak is None or sejak >= REFERENCE_REFRESH_MINUTES * 60

    def _recent_paths(self):
        """Endpoint penarikan tambahan, dalam bentuk yang tercatat di log."""
        return ['/api/external%s' % path for _kunci, path, _model in RECENT_DATASETS]

    def _reference_paths(self):
        """Endpoint cermin referensi, untuk mengenali barisnya di log."""
        return ['/api/external/v1/%s' % resource for resource, _model in REFERENCE_MIRRORS]

    def _seconds_since_attempt(self, paths):
        """Berapa detik sejak endpoint tersebut terakhir **dicoba** ditarik.

        Diambil dari log sinkronisasi, bukan dari kolom tersendiri di konfigurasi.
        Dua alasan:

        1. Percobaan yang gagal pun tercatat, jadi server yang sedang tidak bisa
           dihubungi tidak dicoba ulang oleh setiap halaman yang dibuka.
        2. Menulis kolom di konfigurasi dari jalur halaman berarti menunggu kunci
           barisnya kalau transaksi pemanggil sedang memegang baris itu — dan
           halaman tidak boleh menunggu kunci.
        """
        self.ensure_one()
        terakhir = self.env['presenly.saas.sync.log'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('endpoint', 'in', paths),
        ], order='create_date desc', limit=1)
        if not terakhir:
            return None
        return (fields.Datetime.now() - terakhir.create_date).total_seconds()

    @api.model
    def _refresh_from_page(self):
        """Segarkan cermin karena ada yang membuka halamannya.

        Dijalankan di transaksi tersendiri, dan transaksi itu di-commit sendiri.

        Transaksi tersendiri bukan pilihan gaya: pembacaan daftar ditandai
        `@api.readonly`, sehingga cursornya bisa hanya-baca dan tulisan dari sana
        ditolak PostgreSQL. Transaksi tersendiri juga melepas kunci penjagaan
        waktunya lebih cepat — dilepas saat penarikan selesai, bukan saat halaman
        selesai.

        Hasilnya tetap terlihat oleh pembacaan daftar sesudahnya: PostgreSQL
        membaca dengan READ COMMITTED, jadi tiap perintah melihat keadaan terbaru.

        Seluruh kegagalannya ditelan: halaman tidak boleh gagal karena server
        Presenly sedang tidak bisa dihubungi.
        """
        company_id = self.env.company.id
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                dijalankan = env['presenly.saas.config']._refresh_requests_now(company_id)
                cr.commit()
        except Exception:                      # noqa: BLE001 - halaman tidak boleh gagal
            _logger.exception(
                'presenly_saas: penyegaran cermin dari halaman gagal (company id %s)',
                company_id,
            )
            return False
        return dijalankan

    def _config_for_record(self, record):
        """Konfigurasi yang berhak mengirim record ini, dan catat pemiliknya.

        Record cermin boleh jadi milik perusahaan hasil cermin klien, sedangkan
        konfigurasinya dimiliki perusahaan pemasang. Di database dengan satu
        konfigurasi, `_config_for_company()` sudah cukup. Yang dihindari di sini
        adalah database dengan beberapa konfigurasi: di sana menebak berarti
        mengirim data ke tenant Presenly yang salah.

        Karena itu pemiliknya dicatat pada kontak pertama yang berhasil, lalu
        dipakai terus. Kalau belum pernah tercatat dan konfigurasinya lebih dari
        satu, kirim baliknya ditolak — bukan ditebak.
        """
        tercatat = record.presenly_saas_config_id
        if tercatat and tercatat.enabled and tercatat.active:
            return tercatat

        config = self._config_for_company(record.company_id)
        if config and config != tercatat:
            # Dicatat tanpa memicu kirim balik: penulisan ini bagian dari
            # sinkronisasi, bukan suntingan pengguna.
            record.sudo().with_context(presenly_skip_push=True).write({
                'presenly_saas_config_id': config.id,
            })
        return config

    def _config_for_company(self, company):
        """Konfigurasi yang berlaku untuk perusahaan ini.

        Perusahaan hasil cermin klien **bukan** pemilik integrasi: yang memasang
        dan memiliki integrasi ini adalah perusahaan tempat konfigurasinya dibuat.
        Karena itu pencariannya naik ke perusahaan induk sebelum menyerah.

        Tanpa ini, kirim balik dari data milik perusahaan klien gagal tanpa suara
        — bukan galat, hanya tidak pernah terkirim.
        """
        Config = self.sudo()
        kandidat = company
        while kandidat:
            config = Config.search([
                ('company_id', '=', kandidat.id),
                ('enabled', '=', True),
                ('active', '=', True),
            ], limit=1)
            if config:
                return config
            kandidat = kandidat.parent_id

        # Perusahaan hasil cermin klien biasanya tidak punya induk: Odoo melarang
        # mengubah hierarki perusahaan (`The company hierarchy cannot be changed`),
        # jadi induknya hanya bisa ditetapkan saat pembuatan. Untuk data yang
        # sudah ada, satu-satunya konfigurasi yang masuk akal adalah konfigurasi
        # yang aktif. Kalau ada lebih dari satu, keadaannya ambigu dan itu
        # dilaporkan — memilih salah satunya diam-diam berisiko mengirim data ke
        # tenant Presenly yang salah.
        kandidat = Config.search([('enabled', '=', True), ('active', '=', True)])
        if len(kandidat) == 1:
            return kandidat
        if len(kandidat) > 1:
            _logger.warning(
                'Presenly SaaS: %s milik perusahaan %s, yang bukan pemilik '
                'konfigurasi mana pun, dan ada %s konfigurasi aktif. Kirim balik '
                'dilewati supaya data tidak masuk ke tenant yang salah.',
                company.display_name, company.display_name, len(kandidat),
            )
        return Config.browse()

    def _pull_clients(self):
        """Selaraskan klien Presenly dengan `res.company`.

        Klien yang belum ada dibuat; yang sudah ada diperbarui. Klien yang hilang
        dari respons **tidak** dihapus — hanya dilaporkan — karena menghapus
        perusahaan ikut membawa data lain yang menggantung padanya.

        Mengembalikan ``(ringkasan, error)``.
        """
        self.ensure_one()
        started = fields.Datetime.now()
        path = '/api/external/v1/internal-companies'
        try:
            rows, _meta, _pages = self._fetch_pages(
                lambda params, _client=self._client().get_resource:
                    _client('internal-companies', params),
                {'limit': 500},
            )
        except SaasClientError as exc:
            self._log_pull(path, False, exc, started)
            return {}, redact(exc, self.api_key)

        Perusahaan = self.env['res.company'].sudo()
        ringkasan = {'created': 0, 'updated': 0, 'missing': 0}
        terlihat = set()

        for row in rows:
            if not isinstance(row, dict) or not row.get('id'):
                continue
            client_id = int(row['id'])
            terlihat.add(client_id)
            nilai = {
                'name': row.get('name') or _('Presenly Client %s', client_id),
                'email': row.get('email') or False,
                'phone': row.get('whatsapp_number') or False,
                'presenly_business_sector': row.get('business_sector') or False,
                'presenly_synced_at': fields.Datetime.now(),
            }
            # Tanpa induk, hierarki perusahaan tidak bisa dirapikan di sini: Odoo
            # melarang mengubahnya setelah perusahaan dibuat (`res.company.write`
            # menolak dengan "The company hierarchy cannot be changed"). Jadi
            # perusahaan cermin klien berdiri sendiri, dan pencarian konfigurasi
            # untuk kirim balik mengandalkan konfigurasi aktif — bukan hierarki.
            perusahaan = Perusahaan.search([('presenly_client_id', '=', client_id)], limit=1)
            if perusahaan:
                perusahaan.write(nilai)
                ringkasan['updated'] += 1
            else:
                Perusahaan.create(dict(nilai, presenly_client_id=client_id))
                ringkasan['created'] += 1

        # Klien yang sudah tercermin tetapi tidak ada lagi di respons.
        hilang = Perusahaan.search([
            ('presenly_client_id', '!=', False),
            ('presenly_client_id', 'not in', list(terlihat)),
        ])
        ringkasan['missing'] = len(hilang)
        if hilang:
            _logger.warning(
                'Presenly SaaS: %s klien tidak ada lagi di respons dan tidak dihapus: %s',
                len(hilang), ', '.join(hilang.mapped('name')),
            )

        self._log_pull(path, True, None, started)
        return ringkasan, False

    def _changed_datasets(self):
        """Jenis mana yang berubah sejak penanda terakhirnya.

        Satu permintaan ke API, bukan tujuh. Jawabannya biasanya "tidak ada",
        dan pertanyaan itu ditanyakan setiap kali halaman cermin dibuka — jadi
        yang mahal tidak boleh ikut serta hanya untuk mengetahui tidak ada yang
        perlu dikerjakan.
        """
        self.ensure_one()
        envelope = self._client(
            timeout=INLINE_PULL_TIMEOUT, retry_count=0
        ).get_changes()
        terakhir = envelope.get('data') or {}

        Mark = self.env['presenly.saas.sync.mark'].sudo()
        berubah = []
        for kunci, _path, _model in RECENT_DATASETS:
            waktu_server = terakhir.get(kunci)
            if not waktu_server:
                continue
            penanda = Mark._since(self.company_id, kunci, 0)
            # Belum pernah ditarik: apa pun isinya perlu ditarik.
            if not penanda or parse_datetime(waktu_server) > penanda:
                berubah.append(kunci)
        return berubah

    def _refresh_requests_now(self, company_id):
        """Segarkan cermin karena halamannya dibuka.

        Dijalankan dari pembacaan daftar, jadi seluruh kegagalannya ditelan:
        membuka daftar tidak boleh gagal karena server Presenly sedang tidak bisa
        dihubungi.

        Mengembalikan True kalau ada yang ditarik, False kalau tidak ada yang
        berubah atau penarikannya dilewati.
        """
        config = self.sudo().search([
            ('company_id', '=', company_id),
            ('enabled', '=', True),
            ('active', '=', True),
        ], limit=1)
        if not config or not config.request_auto_refresh:
            return False

        # Kunci penasihat, dan sengaja yang "try": kalau ada penarikan yang
        # sedang berjalan, pemanggil ini langsung menyerah alih-alih menunggu.
        # Menunggu kunci baris akan menahan halaman.
        self.env.cr.execute(
            'SELECT pg_try_advisory_xact_lock(%s, %s)',
            [_REQUEST_LOCK_KEY, company_id],
        )
        if not self.env.cr.fetchone()[0]:
            return False

        try:
            berubah = config._changed_datasets()
        except SaasClientError as exc:
            _logger.warning(
                "Presenly SaaS: pemeriksaan perubahan gagal untuk company id %s: %s",
                company_id, redact(exc, config.api_key),
            )
            return False

        if not berubah:
            # Yang paling sering terjadi: tidak ada yang berubah, dan satu
            # permintaan sudah cukup untuk memastikannya.
            return False

        try:
            _summary, error = config._pull_recent_data(
                datasets=berubah, timeout=INLINE_PULL_TIMEOUT, retry_count=0,
            )
        except Exception:                      # noqa: BLE001 - halaman tidak boleh gagal
            _logger.exception(
                "Presenly SaaS: penyegaran cermin dari halaman gagal (company id %s)",
                company_id,
            )
            return False

        if error:
            _logger.warning(
                "Presenly SaaS: penyegaran cermin dari halaman melaporkan masalah "
                "untuk company id %s: %s", company_id, error,
            )
        return True

    @api.model
    def _cron_pull_recent_all(self):
        """Tarik pengajuan yang berubah untuk setiap koneksi aktif.

        Berjalan jauh lebih sering daripada penarikan periode, dan sengaja hanya
        menyentuh pengajuan: tabelnya kecil, dan penarikan tambahan hanya
        mengambil yang berubah.
        """
        configs = self.sudo().search([('enabled', '=', True), ('active', '=', True)])
        for config in configs:
            try:
                _summary, error = config._pull_recent_data()
            except UserError as exc:           # masalah konfigurasi, bukan galat jauh
                error = str(exc)
            except Exception:                  # noqa: BLE001 - satu tenant tidak boleh menghentikan tenant lain
                _logger.exception(
                    "Presenly SaaS: request sync failed for company %s",
                    config.company_id.display_name,
                )
                error = _('Unexpected error, see the Odoo log.')
            if error:
                _logger.warning(
                    "Presenly SaaS: request sync failed for company %s: %s",
                    config.company_id.display_name,
                    error,
                )
        return True

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
    def _cron_prune_file_cache_all(self):
        """Buang cache berkas yang tidak dipakai cermin mana pun.

        Terpisah dari pemangkasan cermin karena urutannya penting: cache hanya
        boleh dibuang setelah cerminnya dipangkas.
        """
        return self.env['presenly.saas.attachment.sync'].prune_file_cache()

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


        # Cache berkas dibuang setelah cerminnya dipangkas: yang masih dipakai
        # cermin tidak boleh ikut terbuang.
        self.env['presenly.saas.attachment.sync'].prune_file_cache()

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
