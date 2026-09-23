"""Jadwal kerja mingguan: lokasi kerja dan shift per hari, per pegawai.

Presenly menyimpan pola mingguan, bukan penugasan per tanggal: satu baris untuk
setiap hari dalam sepekan, dengan lokasi kerja dan shiftnya, berlaku dalam rentang
`valid_from`–`valid_until`. Yang dipakai pegawai hari ini adalah baris hari ini.

Odoo tidak punya padanan untuk ini. `hr.employee.work_location_id` menunjuk satu
lokasi, dan itu diisi dari penempatan; jadwal hariannya tidak punya tempat. Jadi
polanya disimpan di cermin, dan di `hr.employee` ditampilkan sebagai daftar hari —
tanpa mengubah satu pun kolom native.

Baris yang hilang dari respons **dihapus**, berbeda dari pegawai yang tidak pernah
dihapus. Alasannya: daftar ini diambil utuh dalam sekali tarikan, jadi tidak adanya
sebuah baris berarti hari itu memang tidak dijadwalkan lagi — sedangkan jadwal basi
justru menyesatkan orang yang membacanya.
"""

import logging

from odoo import _, api, fields, models

from odoo.addons.presenly_saas.models.presenly_saas_config import redact
from odoo.addons.presenly_saas.services.saas_client import SaasClientError

_logger = logging.getLogger(__name__)

JADWAL_PATH = '/api/external/v1/weekly-schedules'

HARI = [
    ('mon', 'Monday'),
    ('tue', 'Tuesday'),
    ('wed', 'Wednesday'),
    ('thu', 'Thursday'),
    ('fri', 'Friday'),
    ('sat', 'Saturday'),
    ('sun', 'Sunday'),
]


class PresenlySaasEmployeeSchedule(models.Model):
    """Satu hari dalam pola mingguan seorang pegawai."""

    _name = 'presenly.saas.employee.schedule'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Employee Weekly Schedule (mirror)'
    _order = 'employee_nopeg, day_of_week, valid_from desc'
    _mirror_resource = 'weekly-schedules'

    name = fields.Char(compute='_compute_name', store=True)
    employee_nopeg = fields.Char(string='Nopeg', index=True)
    employee_name = fields.Char(string='Employee')

    day_of_week = fields.Selection(HARI, string='Day', index=True)
    is_workday = fields.Boolean(string='Working Day')

    location_id = fields.Integer(string='Location ID')
    location_name = fields.Char(string='Work Location')
    shift_id = fields.Integer(string='Shift ID')
    shift_name = fields.Char(string='Shift')

    priority = fields.Integer()
    status = fields.Char(string='Status in Presenly')
    valid_from = fields.Date(string='Valid From')
    valid_until = fields.Date(string='Valid Until')

    hr_employee_id = fields.Many2one(
        'hr.employee',
        string='Odoo Employee',
        index=True,
        ondelete='cascade',
        help='Resolved from the nopeg, the same key the employee sync uses.',
    )

    @api.depends('employee_name', 'day_of_week', 'location_name', 'shift_name')
    def _compute_name(self):
        label = dict(HARI)
        for row in self:
            bagian = [row.employee_name or row.employee_nopeg or _('Employee')]
            bagian.append(label.get(row.day_of_week, row.day_of_week or '?'))
            if not row.is_workday:
                bagian.append(_('not a working day'))
            elif row.location_name:
                bagian.append(row.location_name)
            if row.shift_name:
                bagian.append(row.shift_name)
            row.name = ' · '.join(bagian)


class HrEmployee(models.Model):
    """Jadwal mingguan ditampilkan di pegawai native, tanpa kolom baru di sana."""

    _inherit = 'hr.employee'

    presenly_schedule_ids = fields.One2many(
        'presenly.saas.employee.schedule',
        'hr_employee_id',
        string='Work Location by Day',
        readonly=True,
    )


class PresenlySaasConfig(models.Model):
    """Penarikan jadwal mingguan."""

    _inherit = 'presenly.saas.config'

    def _pull_employees(self):
        """Setelah pegawai ditarik, jadwalnya menyusul.

        Dipanggil di sini karena jadwal menunjuk ke pegawai lewat nopeg; pegawai
        itu baru ada setelah tarikan sebelumnya.
        """
        ringkas, error = super()._pull_employees()
        if error:
            return ringkas, error

        ringkas_jadwal, error_jadwal = self._pull_schedules()
        if error_jadwal:
            return ringkas, error_jadwal
        ringkas['schedules'] = ringkas_jadwal
        return ringkas, error

    def _pull_schedules(self):
        """Selaraskan pola mingguan. Mengembalikan ``(ringkasan, error)``."""
        self.ensure_one()
        started = fields.Datetime.now()
        try:
            rows, _meta, _pages = self._fetch_pages(
                lambda params, _client=self._client().get_resource:
                    _client('weekly-schedules', params),
                {'limit': 500},
            )
        except SaasClientError as exc:
            self._log_pull(JADWAL_PATH, False, exc, started)
            return {}, redact(exc, self.api_key)

        Cermin = self.env['presenly.saas.employee.schedule'].sudo()
        Hr = self.env['hr.employee'].sudo().with_context(active_test=False)

        ringkasan = {'created': 0, 'updated': 0, 'removed': 0, 'without_employee': 0}
        terlihat = set()
        pegawai_terlihat = set()

        for row in rows:
            if not isinstance(row, dict) or not row.get('id'):
                continue
            external_id = int(row['id'])
            terlihat.add(external_id)

            pegawai = row.get('employee') if isinstance(row.get('employee'), dict) else {}
            nopeg = (pegawai or {}).get('nopeg') or False
            if nopeg:
                pegawai_terlihat.add(nopeg)

            tempat = row.get('location') if isinstance(row.get('location'), dict) else {}
            shift = row.get('shift') if isinstance(row.get('shift'), dict) else {}

            nilai = {
                'company_id': self.company_id.id,
                'external_id': external_id,
                'employee_nopeg': nopeg,
                'employee_name': (pegawai or {}).get('name') or False,
                'day_of_week': row.get('day_of_week') or False,
                'is_workday': bool(row.get('is_workday')),
                'location_id': int((tempat or {}).get('id') or 0),
                'location_name': (tempat or {}).get('name') or False,
                'shift_id': int((shift or {}).get('id') or 0),
                'shift_name': (shift or {}).get('name') or False,
                'priority': int(row.get('priority') or 0),
                'status': row.get('status') or False,
                'valid_from': row.get('valid_from') or False,
                'valid_until': row.get('valid_until') or False,
            }

            hr = Hr.search([('presenly_nopeg', '=', nopeg)], limit=1) if nopeg else Hr.browse()
            nilai['hr_employee_id'] = hr.id or False
            if nopeg and not hr:
                ringkasan['without_employee'] += 1

            cermin = Cermin.search([
                ('company_id', '=', self.company_id.id), ('external_id', '=', external_id),
            ], limit=1)
            if cermin:
                cermin.write(nilai)
                ringkasan['updated'] += 1
            else:
                Cermin.create(nilai)
                ringkasan['created'] += 1

        # Baris yang hilang dari respons dihapus — tetapi hanya milik pegawai yang
        # memang muncul di respons ini. Kalau tarikannya terpotong, pegawai yang
        # tidak terlihat jangan ikut kehilangan jadwalnya.
        if pegawai_terlihat:
            hilang = Cermin.search([
                ('company_id', '=', self.company_id.id),
                ('employee_nopeg', 'in', list(pegawai_terlihat)),
                ('external_id', 'not in', list(terlihat)),
            ])
            ringkasan['removed'] = len(hilang)
            if hilang:
                hilang.unlink()

        self._log_pull(JADWAL_PATH, True, None, started)
        _logger.info(
            'Presenly SaaS: jadwal mingguan diselaraskan (%s baru, %s diperbarui, '
            '%s dihapus, %s tanpa pegawai).',
            ringkasan['created'], ringkasan['updated'], ringkasan['removed'],
            ringkasan['without_employee'],
        )
        return ringkasan, False
