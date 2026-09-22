import logging

from odoo import api, fields, models

from .presenly_saas_attendance_log import parse_datetime
from .presenly_saas_payload import named_ref, parse_date, person_ref

_logger = logging.getLogger(__name__)


def hours_between(start_time, end_time):
    """Selisih dua jam berbentuk teks `HH:MM:SS`, dalam jam.

    Dihitung di Odoo, dan itu disengaja: server tidak mengirim kolom durasi,
    hanya jam mulai dan jam selesai. Karena angkanya bukan kiriman server,
    kolomnya diberi keterangan supaya tidak dikira nilai resmi.

    Mengembalikan 0.0 bila salah satu jam kosong atau tidak terbaca. Shift yang
    melewati tengah malam (selesai lebih awal dari mulai) juga menghasilkan 0.0,
    bukan angka negatif atau tebakan: lebih baik kosong daripada menyesatkan.
    """
    if not start_time or not end_time:
        return 0.0

    def ke_menit(teks):
        bagian = str(teks).strip().split(':')
        if len(bagian) < 2:
            return None
        try:
            jam, menit = int(bagian[0]), int(bagian[1])
        except ValueError:
            return None
        if not (0 <= jam <= 23 and 0 <= menit <= 59):
            return None
        return jam * 60 + menit

    mulai, selesai = ke_menit(start_time), ke_menit(end_time)
    if mulai is None or selesai is None or selesai <= mulai:
        return 0.0
    return round((selesai - mulai) / 60.0, 2)


class PresenlySaasProject(models.Model):
    """Cermin `GET /v1/projects`.

    Data referensi: tidak punya periode, jadi penarikannya mengganti seluruh
    isi, dan jendela bergulir tidak pernah menghapusnya.
    """

    _name = 'presenly.saas.project'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Project (mirror)'
    _order = 'project_code'

    _mirror_resource = 'projects'

    project_code = fields.Char(string='Project Code', required=True)
    project_name = fields.Char(string='Project Name', required=True)
    sub_code = fields.Char(string='Sub Code')
    description = fields.Text()

    # Kolom dari sistem SIK di hulu. Namanya sengaja tidak diubah menjadi
    # istilah Odoo, supaya tetap bisa dicocokkan dengan sistem asalnya.
    grup = fields.Char(string='SIK Group')
    pk = fields.Char(string='SIK PK')
    has_timesheet = fields.Boolean(string='Has Timesheet')

    internal_company_id = fields.Integer(string='Internal Company ID')
    internal_company_name = fields.Char(string='Internal Company')

    @api.depends('project_code', 'project_name')
    def _compute_display_name(self):
        for project in self:
            project.display_name = project.project_name or project.project_code or '?'
            if project.project_code and project.project_name:
                project.display_name = '%s - %s' % (
                    project.project_code, project.project_name,
                )

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        internal_company = row.get('internal_company')
        if not isinstance(internal_company, dict):
            internal_company = {}
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'project_code': row.get('project_code') or '',
            'project_name': row.get('project_name') or '',
            'sub_code': row.get('sub_code') or False,
            'description': row.get('description') or False,
            'grup': row.get('grup') or False,
            'pk': row.get('pk') or False,
            'has_timesheet': bool(row.get('has_timesheet')),
            'internal_company_id': int(internal_company.get('id') or 0),
            'internal_company_name': internal_company.get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }


class PresenlySaasTimesheet(models.Model):
    """Cermin `GET /v1/timesheets`.

    Data berperiode: mengganti per rentang tanggal, dan ikut jendela bergulir.
    """

    _name = 'presenly.saas.timesheet'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Timesheet (mirror)'
    _order = 'date desc, id desc'

    _mirror_resource = 'timesheets'
    _mirror_date_field = 'date'

    date = fields.Date(required=True, index=True)
    employee_nopeg = fields.Char(string='Nopeg', index=True)
    employee_name = fields.Char(string='Employee', index=True)
    project_code = fields.Char(string='Project Code', index=True)
    project_name = fields.Char(string='Project Name', index=True)

    category = fields.Char(index=True)
    description = fields.Text()
    start_time = fields.Char(string='Start Time')
    end_time = fields.Char(string='End Time')
    hours = fields.Float(
        string='Hours',
        digits=(6, 2),
        help='Derived in Odoo from Start Time and End Time. The Presenly server '
             'sends no duration column, so this number is not an official server '
             'value. It is 0 when either time is missing, or when the shift ends '
             'before it starts (an overnight shift).',
    )

    status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        index=True,
    )
    rating = fields.Float(string='Rating', digits=(2, 1), help='Manager rating, 1.0 to 5.0.')
    comment = fields.Text(string='Manager Comment')
    approver_name = fields.Char(string='Approver')
    shift_name = fields.Char(string='Shift')

    @api.depends('employee_name', 'date', 'project_name')
    def _compute_display_name(self):
        for timesheet in self:
            timesheet.display_name = '%s - %s (%s)' % (
                timesheet.employee_name or '?',
                timesheet.date or '?',
                timesheet.project_name or 'No project',
            )

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        employee = person_ref(row.get('employee'))
        # Proyek datang sebagai {id, code, name}, bukan {id, name}.
        project = row.get('project') if isinstance(row.get('project'), dict) else {}
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'date': parse_date(row.get('date')),
            'employee_nopeg': employee.get('nopeg') or False,
            'employee_name': employee.get('name') or False,
            'project_code': project.get('code') or False,
            'project_name': project.get('name') or False,
            'category': row.get('category') or False,
            'description': row.get('description') or False,
            'start_time': row.get('start_time') or False,
            'end_time': row.get('end_time') or False,
            'hours': hours_between(row.get('start_time'), row.get('end_time')),
            'status': row.get('status') or False,
            'rating': float(row.get('rating') or 0.0),
            'comment': row.get('comment') or False,
            'approver_name': person_ref(row.get('approver')).get('name') or False,
            'shift_name': named_ref(row.get('shift')).get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }
