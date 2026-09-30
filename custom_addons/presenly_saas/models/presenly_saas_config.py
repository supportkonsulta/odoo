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

# Jeda minimum sebelum satu cermin referensi ditarik lagi dari halamannya.
# Halamannya memang menarik sendiri saat dibuka — itu yang membuat perubahannya
# langsung terlihat — tetapi tanpa jeda ini, memindah bulan di kalender atau
# mengurutkan ulang daftar berarti satu penarikan utuh setiap kali. Sepuluh
# detik cukup untuk menahan itu dan masih terasa langsung bagi yang membukanya.
INLINE_REFERENCE_MIN_SECONDS = 10

# Jeda minimum per jenis untuk penyegaran yang dipicu webhook. Presensi berubah
# setiap kali orang masuk dan keluar; menarik rentang berbulan-bulan pada tiap
# ketukan jauh lebih mahal daripada manfaatnya, sedangkan perubahannya sendiri
# sudah ditangani tarikan tambahan yang berjalan tiap 15 menit. Yang perlu jalur
# ini adalah penghapusan, dan ia tidak perlu secepat itu.
WEBHOOK_PULL_MIN_SECONDS = 120

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
        help='What the guard API does when the status is negative.\n'
             'Off: status is visible on the dashboard only.\n'
             'Warn only: the dashboard plus a warning banner in the backend.\n'
             'Enforce: the banner plus presenly.saas.guard.check() raising for '
             'the modules that call it. It does not close the backend by '
             'itself; Block Access does that.',
    )
    grace_days = fields.Integer(
        string='Grace Period (days)',
        default=7,
        help='How long a snapshot that the Presenly server has not confirmed '
             'stays acceptable. Zero turns the offline part of the check off '
             'entirely. A network failure never blocks on its own before this '
             'many days have passed, and only when Block Access is enforced.',
    )
    show_banner = fields.Boolean(
        string='Show Banner',
        default=True,
        help='Display the subscription banner in the backend when the status '
             'needs attention.',
    )
    block_mode = fields.Selection(
        [
            ('off', 'Off'),
            ('dry_run', 'Dry run'),
            ('enforce', 'Enforce'),
        ],
        string='Block Access',
        default='off',
        required=True,
        help='What happens to the Odoo backend when the subscription is not '
             'active. Off: nothing is closed, the banner still tells the '
             'story. Dry run: every request that would be refused is counted '
             'and logged, and let through. Enforce: the backend is closed for '
             'this company, except signing in, the blocked page, and the '
             'webhook receiver.\n'
             'This is independent of Guard Mode: Guard Mode governs the API '
             'other modules call, this governs the gate.',
    )
    block_override_until = fields.Datetime(
        string='Temporary Access Until',
        help='Let this company keep working until this moment, even when the '
             'subscription is not active. Meant for support while a renewal is '
             'being settled, not as a second way to run without paying. Every '
             'use is recorded in the sync log.',
    )
    block_override_reason = fields.Char(
        string='Reason for Temporary Access',
        help='Why the temporary access was granted. Read back by whoever finds '
             'the installation open when they expected it closed.',
    )
    block_override_user_id = fields.Many2one(
        'res.users',
        string='Temporary Access Granted By',
        readonly=True,
        copy=False,
    )
    dry_run_blocked_count = fields.Integer(
        string='Requests That Would Have Been Blocked',
        readonly=True,
        copy=False,
    )
    dry_run_noted_at = fields.Datetime(readonly=True, copy=False)
    blocked_since = fields.Datetime(
        string='Blocked Since', readonly=True, copy=False,
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

    def _pull_reference_data(self, resources=None, timeout=None, retry_count=None):
        """Tarik resource referensi. Mengembalikan ``(summary, error)``.

        `resources` memilih sebagian saja — dipakai halaman yang membuka satu
        cermin referensi dan hanya perlu cermin itu yang segar, bukan keenamnya.
        Tanpa argumen, seluruhnya ditarik seperti sebelumnya.
        """
        self.ensure_one()
        self._require_enabled()
        client = self._client(timeout=timeout, retry_count=retry_count)
        summary = {}
        dipilih = [
            (resource, model_name) for resource, model_name in REFERENCE_MIRRORS
            if not resources or resource in resources
        ]

        for resource, model_name in dipilih:
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

    def _pull_window(self):
        """(bulan, tahun) yang dicakup penarikan periodik, yang terlama dulu."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        months = max(1, int(self.pull_months or 1))
        akhir = date(today.year, today.month, 1)
        hasil = []
        for offset in range(months - 1, -1, -1):
            bulan = akhir - relativedelta(months=offset)
            hasil.append((bulan.month, bulan.year))
        return hasil

    def _pull_dataset(self, resource):
        """Segarkan satu cermin karena server memberi tahu ada perubahan di sana.

        Yang penting di sini bukan perubahannya — itu sudah ditangani tarikan
        tambahan yang murah — melainkan **penghapusan**. Baris yang hilang dari
        server hanya ketahuan dengan mengganti rentangnya, bukan dengan
        menyisipkan yang berubah. Tanpa jalur ini, menghapus pengajuan di
        aplikasi menyisakan salinannya di Odoo sampai cron harian berjalan.

        Ada jeda minimum per jenis. Presensi berubah setiap kali orang masuk dan
        keluar, dan menarik rentang berbulan-bulan pada tiap ketukan jauh lebih
        mahal daripada manfaatnya; perubahannya sendiri tetap terambil oleh
        tarikan tambahan yang berjalan tiap 15 menit.
        """
        self.ensure_one()
        if not resource:
            return False
        jalur = '/api/external/v1/%s' % resource
        sejak = self._seconds_since_attempt([jalur])
        if sejak is not None and sejak < WEBHOOK_PULL_MIN_SECONDS:
            return False

        if resource in dict(REFERENCE_MIRRORS):
            _ringkas, error = self._pull_reference_data(
                resources=[resource], timeout=INLINE_PULL_TIMEOUT, retry_count=0,
            )
            return error

        if resource == 'attendance-logs':
            # Presensi yang baru dihapus hampir selalu yang terbaru, jadi bulan
            # berjalan saja. Menarik seluruh jendela pada tiap ketukan absen
            # terlalu mahal untuk sesuatu yang jarang terjadi — sedangkan
            # perubahannya sendiri sudah diambil tarikan tambahan.
            bulan, tahun = self._pull_window()[-1]
            _ringkas, error = self._pull_attendance(bulan, tahun)
            return error

        if resource == 'placements' and hasattr(self, '_pull_placements'):
            # Perubahan penempatan: yang berubah bukan pegawainya, melainkan
            # penempatannya. Menarik pegawai hanya menambah pekerjaan yang tidak
            # ada hubungannya, dan justru penempatan inilah yang menentukan
            # cabang serta akses perusahaan seseorang.
            #
            # `hasattr` dipakai karena penempatan hanya ada bila `presenly_saas_hr`
            # terpasang, sedangkan berkas ini milik modul tanpa `hr`.
            _ringkas, error = self._pull_placements()
            return error

        if resource not in dict(PERIOD_DATASETS):
            # Jenis yang tidak dikenal: tarikan biasa yang menanganinya.
            return False

        for bulan, tahun in self._pull_window():
            _ringkas, error = self._pull_period_datasets(
                bulan, tahun, resources=[resource],
            )
            if error:
                return error
        return False

    def _pull_period_range(self, end_month, end_year, months_back=1):
        """Tarik beberapa bulan ke belakang, berakhir di bulan yang dipilih.

        Satu bulan berisi log presensi dan lima jenis pengajuan. Mengembalikan
        ``(summary, error)`` dengan total gabungan dan daftar bulan yang
        terpotong.
        """
        self.ensure_one()
        self._require_enabled()

        months = max(1, int(months_back or 1))
        end = date(int(end_year), int(end_month), 1)

        total = {'logs': 0, 'months': 0, 'datasets': {}}
        truncated = []
        periods = []

        for offset in range(months - 1, -1, -1):
            current = end - relativedelta(months=offset)
            summary, error = self._pull_attendance(current.month, current.year)
            if error:
                return total, error
            total['logs'] += summary['logs']
            truncated.extend(summary['truncated'])

            datasets, error = self._pull_period_datasets(current.month, current.year)
            if error:
                return total, error
            for resource, count in datasets['rows'].items():
                total['datasets'][resource] = total['datasets'].get(resource, 0) + count
            truncated.extend(datasets['truncated'])

            total['months'] += 1
            periods.append(summary['period'])

        total['periods'] = periods
        total['truncated'] = truncated
        return total, False

    def _pull_attendance(self, month, year):
        """Tarik log presensi untuk satu bulan.

        Mengembalikan ringkasan berisi jumlah baris yang ditulis, dan catatan
        bila penarikan berhenti karena batas halaman. Cermin yang tidak lengkap
        tidak boleh tampak seperti data yang lengkap.
        """
        self.ensure_one()
        self._require_enabled()
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])

        summary = {'period': '%02d/%s' % (month, year), 'logs': 0, 'truncated': []}

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

        return summary, False

    def _pull_period_datasets(self, month, year, resources=None):
        """Tarik pengajuan dan timesheet untuk satu bulan.

        `resources` memilih sebagian saja — dipakai webhook, yang hanya perlu
        satu jenis yang berubah.

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
        dipilih = [
            (resource, model_name) for resource, model_name in PERIOD_DATASETS
            if not resources or resource in resources
        ]
        for resource, model_name in dipilih:
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
            except SaasClientError as exc:
                error = redact(exc, self.api_key)
                self._log_pull(path, False, exc, started)
                return summary, error
            except Exception as exc:  # noqa: BLE001 - dicatat, bukan dibiarkan hilang
                # Galat tak terduga di satu jenis tidak boleh lewat tanpa jejak:
                # tanpa catatan ini, jenis yang gagal hanya terlihat sebagai
                # daftar yang kosong, dan tidak ada yang tahu ke mana mencarinya.
                _logger.exception(
                    'Presenly SaaS: penarikan %s untuk %02d/%s gagal',
                    resource, month, year,
                )
                self._log_pull(path, False, exc, started)
                return summary, redact(exc, self.api_key)

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
        summary = {'datasets': {}, 'server_time': None,
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
        if diminta is not None and not diminta:
            return summary, False

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

    @api.model
    def _reference_resource_names(self):
        """Nama resource yang cerminnya adalah cermin referensi.

        Dipakai cermin untuk tahu apakah halamannya perlu menarik dirinya
        sendiri; disediakan sebagai metode supaya daftarnya cuma ada di
        `REFERENCE_MIRRORS`, bukan disalin ke tempat lain.
        """
        return {resource for resource, _model in REFERENCE_MIRRORS}

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
    def _refresh_recent_from_decision(self):
        """Segarkan perubahan terakhir di **transaksi tersendiri**, lalu commit.

        Dipakai jalur keputusan persetujuan, dan dua kali: sebelum keputusan
        dikirim (supaya levelnya yang benar), dan sesudah server menolak (supaya
        keadaannya yang baru yang terlihat).

        Transaksi tersendiri bukan pilihan gaya. Jalur penolakan berakhir dengan
        pemberitahuan alih-alih galat, tetapi pemanggilnya bisa saja membatalkan
        transaksi karena sebab lain - dan penyegaran yang ikut batal berarti
        layarnya tetap menampilkan keadaan yang sudah dibantah server.

        Mengembalikan pesan kegagalan sebagai teks, atau ``''`` bila berhasil.
        Kegagalannya tidak dilempar: keputusannya sudah terkirim, dan gagal
        menyegarkan bukan alasan membatalkan kabar itu.
        """
        self.ensure_one()
        config_id = self.id
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                _ringkas, error = env['presenly.saas.config'].browse(
                    config_id,
                )._pull_recent_data()
                cr.commit()
        except Exception as exc:                  # noqa: BLE001 - hanya dilaporkan
            _logger.exception(
                'presenly_saas: penyegaran sebelum/sesudah keputusan gagal '
                '(config id %s)', config_id,
            )
            return str(exc)
        return error or ''

    def _refresh_from_page(self, resource=None):
        """Segarkan cermin karena ada yang membuka halamannya.

        `resource` menyebut cermin yang halamannya sedang dibuka. Cermin
        referensi memakainya untuk menarik dirinya sendiri — tanpa itu, satu-
        satunya yang menyegarkannya adalah cron, dan halamannya bisa menampilkan
        hari libur yang sudah diubah di aplikasi.

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

        Konfigurasinya dicari lewat `_config_for_company`, **bukan** lewat
        pencarian langsung pada perusahaan yang sedang aktif. Pengguna cabang
        berperusahaan aktif perusahaan cabang, dan di sana tidak ada konfigurasi
        apa pun - pencarian langsung membuat penyegaran halaman diam-diam tidak
        pernah berjalan untuk mereka, walaupun koneksinya menyala.
        """
        config = self.sudo()._config_for_company(self.env.company)
        if not config:
            return False
        config_id = config.id
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                dijalankan = env['presenly.saas.config']._refresh_requests_now(
                    config_id, resource,
                )
                cr.commit()
        except Exception:                      # noqa: BLE001 - halaman tidak boleh gagal
            _logger.exception(
                'presenly_saas: penyegaran cermin dari halaman gagal (config id %s)',
                config_id,
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

        # Klien yang baru ada bisa jadi cabang yang tadinya belum punya perusahaan
        # Odoo, sehingga penempatan yang menunjuknya belum bisa diterapkan. Tanpa
        # langkah ini, perusahaan cabangnya muncul seketika tetapi daftar cabang
        # pegawai dan akses perusahaannya baru menyusul pada tarikan pegawai
        # berikutnya, yaitu sehari kemudian — dan itu terbaca sebagai "webhooknya
        # tidak bekerja", padahal yang tertinggal hanya akibatnya.
        #
        # `getattr` dan `hasattr` karena penempatan hanya ada bila `presenly_saas_hr`
        # terpasang, sedangkan berkas ini milik modul tanpa `hr`.
        if (ringkasan['created'] or ringkasan['updated']) and getattr(
                self, 'sync_employee_placements', False) and hasattr(
                self, '_pull_placements'):
            ringkasan_tempat, error_tempat = self._pull_placements()
            ringkasan['placements'] = ringkasan_tempat
            if error_tempat:
                return ringkasan, error_tempat

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

    def _pull_reference_now(self, resource):
        """Tarik satu cermin referensi karena halamannya dibuka.

        Tidak melempar: pemanggilnya adalah pembacaan daftar, dan halaman tidak
        boleh gagal karena server Presenly sedang tidak bisa dihubungi.
        """
        self.ensure_one()
        path = '/api/external/v1/%s' % resource
        sejak = self._seconds_since_attempt([path])
        if sejak is not None and sejak < INLINE_REFERENCE_MIN_SECONDS:
            return False
        try:
            _summary, error = self._pull_reference_data(
                resources=[resource], timeout=INLINE_PULL_TIMEOUT, retry_count=0,
            )
        except Exception:                      # noqa: BLE001 - halaman tidak boleh gagal
            _logger.exception(
                'presenly_saas: penyegaran cermin %s dari halaman gagal', resource,
            )
            return False
        if error:
            _logger.warning(
                'Presenly SaaS: penyegaran cermin %s dari halaman melaporkan '
                'masalah: %s', resource, error,
            )
        return True

    def _refresh_requests_now(self, config_id, resource=None):
        """Segarkan cermin karena halamannya dibuka.

        `config_id` sudah dipilih pemanggilnya, dan pemilihannya sengaja tidak
        diulang di sini: perusahaan pengguna cabang berbeda dari perusahaan
        pemilik koneksi, dan pencarian langsung pada perusahaan yang aktif membuat
        penyegarannya tidak pernah berjalan.

        Dijalankan dari pembacaan daftar, jadi seluruh kegagalannya ditelan:
        membuka daftar tidak boleh gagal karena server Presenly sedang tidak bisa
        dihubungi.

        Dijalankan di transaksi tersendiri, jadi yang dikembalikannya hanya
        penanda: True kalau ada yang ditarik, False kalau tidak ada yang berubah
        atau penarikannya dilewati.
        """
        config = self.sudo().browse(config_id).exists()
        if not config or not config.enabled or not config.active:
            return False
        company_id = config.company_id.id

        if not config.request_auto_refresh:
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

        if resource and resource in dict(REFERENCE_MIRRORS):
            # Halaman cermin referensi menarik dirinya sendiri. Jenis yang lain
            # tidak punya penanda perubahan yang murah, dan tabelnya kecil —
            # jadi yang dibandingkan bukan "ada perubahan?", melainkan "kapan
            # terakhir dicoba?", supaya tidak ditarik berulang-ulang.
            return config._pull_reference_now(resource)

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
