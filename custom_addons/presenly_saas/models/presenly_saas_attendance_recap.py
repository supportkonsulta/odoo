import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PresenlySaasAttendanceRecap(models.Model):
    """Cermin rekap presensi dari `GET /v1/presenly/attendance-recap`.

    Agregat per pegawai per bulan. Sama seperti log presensi, ini cermin yang
    diganti saat penarikan, bukan arsip.
    """

    _name = 'presenly.saas.attendance.recap'
    _description = 'Presenly Attendance Recap (mirror)'
    _order = 'year desc, month desc, employee_name'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    user_id = fields.Integer(
        string='Employee ID (SaaS)', required=True, index=True,
        aggregator=False,
    )
    employee_name = fields.Char(string='Employee')
    employee_nopeg = fields.Char(string='Nopeg')
    project_name = fields.Char(string='Project')

    month = fields.Integer(required=True)
    year = fields.Integer(required=True)

    attendance_count = fields.Integer(string='Attendance Count')
    total_late_minutes = fields.Integer(string='Total Late (minutes)')
    absent_count = fields.Integer(string='Absent Count')

    fetched_at = fields.Datetime(readonly=True, index=True)
    raw_payload = fields.Json(string='Raw Payload')

    _company_period_user_uniq = models.Constraint(
        'unique(company_id, year, month, user_id)',
        'An employee may only appear once per month per company.',
    )

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None,
                        count_limit=None):
        """Segarkan cermin sebelum daftarnya dibaca.

        Model ini tidak mewarisi `presenly.saas.mirror.mixin` — radas penulisannya
        sendiri — sehingga pemicu yang dipasang di mixin itu tidak berlaku di
        sini. Tanpa penimpaan ini, membuka daftar presensi tidak menarik apa pun,
        dan absensi baru dari aplikasi tidak pernah muncul.
        """
        # Hanya halaman pertama. Menggulir, mengurutkan ulang, dan mencari juga
        # memanggil metode ini; tanpa syarat ini satu kali membuka daftar yang
        # panjang bisa memicu belasan penarikan.
        if not offset:
            self.env['presenly.saas.config']._refresh_from_page()
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit, order=order,
            count_limit=count_limit,
        )

    @api.depends('employee_name', 'month', 'year')
    def _compute_display_name(self):
        for recap in self:
            recap.display_name = '%s - %02d/%s' % (
                recap.employee_name or '?',
                recap.month or 0,
                recap.year or '?',
            )

    @api.model
    def _values_from_payload(self, company, row):
        if not isinstance(row, dict) or not row.get('user_id'):
            return None

        user = row.get('user') if isinstance(row.get('user'), dict) else {}
        return {
            'company_id': company.id,
            'user_id': int(row['user_id']),
            'employee_name': user.get('name') or False,
            'employee_nopeg': user.get('nopeg') or False,
            'project_name': user.get('project') or False,
            'month': int(row.get('month') or 0),
            'year': int(row.get('year') or 0),
            'attendance_count': int(row.get('attendance_count') or 0),
            'total_late_minutes': int(row.get('total_late_minutes') or 0),
            'absent_count': int(row.get('absent_count') or 0),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }

    @api.model
    def _replace_scope(self, company, month, year):
        stale = self.sudo().search([
            ('company_id', '=', company.id),
            ('month', '=', month),
            ('year', '=', year),
        ])
        if stale:
            stale.unlink()
        return len(stale)

    @api.model
    def _upsert_rows(self, company, rows):
        Recap = self.sudo()
        seen = set()
        written = 0
        for row in rows:
            values = self._values_from_payload(company, row)
            if not values:
                continue
            key = (values['user_id'], values['month'], values['year'])
            if key in seen:
                continue
            seen.add(key)
            existing = Recap.search([
                ('company_id', '=', company.id),
                ('user_id', '=', values['user_id']),
                ('month', '=', values['month']),
                ('year', '=', values['year']),
            ], limit=1)
            if existing:
                existing.write(values)
            else:
                Recap.create(values)
            written += 1
        return written
