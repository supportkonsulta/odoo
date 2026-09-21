import logging

from odoo import api, fields, models

from .presenly_saas_attendance_log import parse_datetime

_logger = logging.getLogger(__name__)


class PresenlySaasWorkLocation(models.Model):
    """Cermin `GET /v1/work-locations`."""

    _name = 'presenly.saas.work.location'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Work Location (cermin)'
    _order = 'name'

    _mirror_resource = 'work-locations'

    name = fields.Char(required=True)
    address = fields.Char()
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    radius_meters = fields.Integer(string='Radius (m)')
    timezone = fields.Char()
    attendance_type = fields.Char(string='Tipe Absen')
    is_active = fields.Boolean()

    internal_company_id = fields.Integer(string='ID Perusahaan Internal')
    internal_company_name = fields.Char(string='Perusahaan Internal')
    project_id = fields.Integer(string='ID Proyek')
    project_name = fields.Char(string='Proyek')

    @api.depends('name')
    def _compute_display_name(self):
        for location in self:
            location.display_name = location.name

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        company_ref = row.get('internal_company') if isinstance(row.get('internal_company'), dict) else {}
        project = row.get('project') if isinstance(row.get('project'), dict) else {}
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'name': row.get('name') or '',
            'address': row.get('address') or False,
            'latitude': float(row.get('latitude') or 0.0),
            'longitude': float(row.get('longitude') or 0.0),
            'radius_meters': int(row.get('radius_meters') or 0),
            'timezone': row.get('timezone') or False,
            'attendance_type': row.get('attendance_type') or False,
            'is_active': bool(row.get('is_active')),
            'internal_company_id': int(company_ref.get('id') or 0),
            'internal_company_name': company_ref.get('name') or False,
            'project_id': int(project.get('id') or 0),
            'project_name': project.get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }


class PresenlySaasShift(models.Model):
    """Cermin `GET /v1/shifts`."""

    _name = 'presenly.saas.shift'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Shift (cermin)'
    _order = 'shift_name'

    _mirror_resource = 'shifts'

    shift_name = fields.Char(required=True)
    # Jam dikirim sebagai teks "07:30:00", apa adanya dari server.
    start_time = fields.Char(string='Jam Mulai')
    end_time = fields.Char(string='Jam Selesai')
    late_index = fields.Integer(string='Indeks Keterlambatan')

    location_id = fields.Integer(string='ID Lokasi')
    location_name = fields.Char(string='Lokasi')

    @api.depends('shift_name', 'location_name')
    def _compute_display_name(self):
        for shift in self:
            shift.display_name = '%s - %s' % (shift.shift_name or '?', shift.location_name or '?')

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        location = row.get('location') if isinstance(row.get('location'), dict) else {}
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'shift_name': row.get('shift_name') or '',
            'start_time': row.get('start_time') or False,
            'end_time': row.get('end_time') or False,
            'late_index': int(row.get('late_index') or 0),
            'location_id': int(location.get('id') or 0),
            'location_name': location.get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }


class PresenlySaasAttendanceMode(models.Model):
    """Cermin `GET /v1/attendance-modes`.

    Mode absen menentukan penegakan radius: hanya mode yang bernama "Work From
    Office" yang diwajibkan berada dalam geofence.
    """

    _name = 'presenly.saas.attendance.mode'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Attendance Mode (cermin)'
    _order = 'name'

    _mirror_resource = 'attendance-modes'

    name = fields.Char(required=True)

    @api.depends('name')
    def _compute_display_name(self):
        for mode in self:
            mode.display_name = mode.name

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'name': row.get('name') or '',
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }


class PresenlySaasHoliday(models.Model):
    """Cermin `GET /v1/holidays`."""

    _name = 'presenly.saas.holiday'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Holiday (cermin)'
    _order = 'date desc'

    _mirror_resource = 'holidays'

    date = fields.Date(required=True)
    name = fields.Char(required=True)
    holiday_type = fields.Char(string='Tipe')

    location_id = fields.Integer(string='ID Lokasi')
    location_name = fields.Char(string='Lokasi')

    @api.depends('name', 'date')
    def _compute_display_name(self):
        for holiday in self:
            holiday.display_name = '%s (%s)' % (holiday.name or '?', holiday.date or '?')

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        location = row.get('location') if isinstance(row.get('location'), dict) else {}
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'date': row.get('date') or False,
            'name': row.get('name') or '',
            'holiday_type': row.get('type') or False,
            'location_id': int(location.get('id') or 0),
            'location_name': location.get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }


class PresenlySaasWorkDaySetup(models.Model):
    """Cermin `GET /v1/work-day-setups`."""

    _name = 'presenly.saas.work.day.setup'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Work Day Setup (cermin)'
    _order = 'year desc, location_name'

    _mirror_resource = 'work-day-setups'

    year = fields.Integer(required=True)
    jan = fields.Integer(string='Jan')
    feb = fields.Integer(string='Feb')
    mar = fields.Integer(string='Mar')
    apr = fields.Integer(string='Apr')
    may = fields.Integer(string='Mei')
    jun = fields.Integer(string='Jun')
    jul = fields.Integer(string='Jul')
    aug = fields.Integer(string='Agu')
    sep = fields.Integer(string='Sep')
    oct = fields.Integer(string='Okt')
    nov = fields.Integer(string='Nov')
    dec = fields.Integer(string='Des')
    total_days = fields.Integer(string='Total Hari Kerja')

    location_id = fields.Integer(string='ID Lokasi')
    location_name = fields.Char(string='Lokasi')

    @api.depends('year', 'location_name')
    def _compute_display_name(self):
        for setup in self:
            setup.display_name = '%s - %s' % (setup.location_name or '?', setup.year or '?')

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        location = row.get('location') if isinstance(row.get('location'), dict) else {}
        months = {
            month: int(row.get(month) or 0)
            for month in ('jan', 'feb', 'mar', 'apr', 'may', 'jun',
                          'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
        }
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'year': int(row.get('year') or 0),
            **months,
            'total_days': int(row.get('total_days') or 0),
            'location_id': int(location.get('id') or 0),
            'location_name': location.get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }
