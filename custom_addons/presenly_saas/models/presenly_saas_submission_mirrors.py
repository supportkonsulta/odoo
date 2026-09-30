import logging

from odoo import api, fields, models

from .presenly_saas_approval import (
    approval_step_commands,
    approval_summary_values,
    normalize_status,
)
from .presenly_saas_attendance_log import parse_datetime
from .presenly_saas_payload import named_ref as _named
from .presenly_saas_payload import parse_date, person_ref as _person

_logger = logging.getLogger(__name__)

# Urutan bawaan kelima pengajuan: yang paling baru **dibuat** di Presenly di
# atas, bukan yang tanggal kejadiannya paling akhir.
#
# Kolom tanggalnya sendiri bukan patokan yang benar untuk itu. Cuti diajukan
# untuk tanggal yang bisa jauh di depan, koreksi presensi untuk tanggal yang
# sudah lewat, dan tukar shift untuk tanggal yang belum tentu disetujui — jadi
# daftar yang diurutkan dengan tanggal kejadiannya terlihat acak bagi orang yang
# baru saja mengirim pengajuan. `source_created_at` adalah `created_at` dari
# server: kapan pengajuannya dibuat.
ORDER_PENGAJUAN = 'source_created_at desc, id desc'


class PresenlySaasLeave(models.Model):
    """Cermin `GET /v1/leaves` — pengajuan cuti."""

    _name = 'presenly.saas.leave'
    _inherit = ['presenly.saas.mirror.mixin', 'presenly.saas.submission.mixin',
                'presenly.saas.attachment.mixin', 'mail.thread']
    _description = 'Presenly Leave Request (mirror)'
    _order = ORDER_PENGAJUAN

    _mirror_resource = 'leaves'
    _mirror_date_field = 'leave_date'

    reference_number = fields.Char(string='Request Number', index=True)
    employee_nopeg = fields.Char(string='Nopeg', index=True)
    employee_name = fields.Char(string='Employee', index=True)
    leave_type_name = fields.Char(string='Leave Type')
    location_name = fields.Char(string='Work Location')

    leave_date = fields.Date(string='Request Date', index=True)
    start_date = fields.Date(string='Start')
    end_date = fields.Date(string='Finished')
    total_days = fields.Float(string='Number of Days', digits=(6, 2))
    purpose = fields.Text(string='Purpose')
    leave_address = fields.Text(string='Address During Leave')

    # `status` dan `status_raw` datang dari mixin pengajuan; keduanya sama untuk
    # kelima jenis pengajuan.
    approver_name = fields.Char(string='Approver')
    approved_at = fields.Datetime(string='Approved At')

    approval_step_ids = fields.One2many(
        'presenly.saas.approval.step.leave', 'leave_id', string='Approval Steps',
    )

    @api.depends('reference_number', 'employee_name', 'leave_date')
    def _compute_display_name(self):
        for leave in self:
            label = leave.reference_number or 'Leave'
            if leave.employee_name:
                label = '%s — %s' % (label, leave.employee_name)
            leave.display_name = label

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        employee = _person(row.get('employee'))
        status, status_raw = normalize_status(row.get('status'))
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'reference_number': row.get('reference_number') or False,
            'employee_nopeg': employee.get('nopeg') or False,
            'employee_name': employee.get('name') or False,
            'leave_type_name': _named(row.get('leave_type')).get('name') or False,
            'location_name': _named(row.get('location')).get('name') or False,
            # Id lokasinya dipakai untuk menurunkan cabang. Namanya tidak
            # dipakai untuk itu: nama bisa berubah, id tidak.
            'location_id': _named(row.get('location')).get('id') or 0,
            'leave_date': parse_date(row.get('leave_date')),
            'start_date': parse_date(row.get('start_date')),
            'end_date': parse_date(row.get('end_date')),
            'total_days': float(row.get('total_days') or 0.0),
            'purpose': row.get('purpose') or False,
            'leave_address': row.get('leave_address') or False,
            'file_path': row.get('certificate_file') or False,
            'status': status,
            'status_raw': status_raw,
            'approver_name': _person(row.get('approver')).get('name') or False,
            'approved_at': parse_datetime(row.get('approved_at')),
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
            **approval_summary_values(row),
            'approval_step_ids': approval_step_commands(row),
        }


class PresenlySaasOvertime(models.Model):
    """Cermin `GET /v1/overtimes` — pengajuan lembur."""

    _name = 'presenly.saas.overtime'
    _inherit = ['presenly.saas.mirror.mixin', 'presenly.saas.submission.mixin']
    _description = 'Presenly Overtime Request (mirror)'
    _order = ORDER_PENGAJUAN

    _mirror_resource = 'overtimes'
    _mirror_date_field = 'overtime_date'

    employee_nopeg = fields.Char(string='Nopeg', index=True)
    employee_name = fields.Char(string='Employee', index=True)
    location_name = fields.Char(string='Work Location')

    overtime_date = fields.Date(string='Overtime Date', index=True)
    purpose = fields.Text(string='Purpose')
    start_time = fields.Char(string='Start Time')
    end_time = fields.Char(string='End Time')
    total_hours = fields.Float(string='Number of Hours', digits=(6, 2))
    day_type = fields.Char(string='Day Type')
    within_radius = fields.Boolean(string='Within Radius')
    overtime_pay = fields.Float(string='Overtime Pay', digits=(16, 2))

    # Lembur memakai kolom `approval_status` dengan penanda lama Y/N/T di sisi
    # Presenly. Nilainya dipetakan ke `status` dari mixin pengajuan, dan nilai
    # aslinya tetap disimpan di `status_raw`.
    approver_name = fields.Char(string='Approver')

    approval_step_ids = fields.One2many(
        'presenly.saas.approval.step.overtime', 'overtime_id',
        string='Approval Steps',
    )

    @api.depends('employee_name', 'overtime_date')
    def _compute_display_name(self):
        for overtime in self:
            overtime.display_name = '%s — %s' % (
                overtime.employee_name or 'Overtime', overtime.overtime_date or '',
            )

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        employee = _person(row.get('employee'))
        status, status_raw = normalize_status(row.get('approval_status'))
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'employee_nopeg': employee.get('nopeg') or False,
            'employee_name': employee.get('name') or False,
            'location_name': _named(row.get('location')).get('name') or False,
            # Id lokasinya dipakai untuk menurunkan cabang. Namanya tidak
            # dipakai untuk itu: nama bisa berubah, id tidak.
            'location_id': _named(row.get('location')).get('id') or 0,
            'overtime_date': parse_date(row.get('overtime_date')),
            'purpose': row.get('purpose') or False,
            'start_time': row.get('start_time') or False,
            'end_time': row.get('end_time') or False,
            'total_hours': float(row.get('total_hours') or 0.0),
            'day_type': row.get('day_type') or False,
            'within_radius': bool(row.get('within_radius')),
            'overtime_pay': float(row.get('overtime_pay') or 0.0),
            'status': status,
            'status_raw': status_raw,
            'approver_name': _person(row.get('approver')).get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
            **approval_summary_values(row),
            'approval_step_ids': approval_step_commands(row),
        }


class PresenlySaasMedicalCertificate(models.Model):
    """Cermin `GET /v1/medical-certificates` — surat keterangan dokter."""

    _name = 'presenly.saas.medical.certificate'
    _inherit = ['presenly.saas.mirror.mixin', 'presenly.saas.submission.mixin',
                'presenly.saas.attachment.mixin', 'mail.thread']
    _description = 'Presenly Medical Certificate (mirror)'
    _order = ORDER_PENGAJUAN

    _mirror_resource = 'medical-certificates'
    _mirror_date_field = 'certificate_date'

    dc_number = fields.Char(string='Certificate Number', index=True)
    employee_nopeg = fields.Char(string='Nopeg', index=True)
    employee_name = fields.Char(string='Employee', index=True)
    location_name = fields.Char(string='Work Location')

    certificate_date = fields.Date(string='Certificate Date', index=True)
    start_date = fields.Date(string='Start')
    end_date = fields.Date(string='Finished')
    reason = fields.Text(string='Reason')

    approver_name = fields.Char(string='Approver')
    approved_at = fields.Datetime(string='Approved At')

    approval_step_ids = fields.One2many(
        'presenly.saas.approval.step.medical.certificate', 'certificate_id',
        string='Approval Steps',
    )

    @api.depends('dc_number', 'employee_name')
    def _compute_display_name(self):
        for certificate in self:
            certificate.display_name = '%s — %s' % (
                certificate.dc_number or 'Medical Certificates',
                certificate.employee_name or '',
            )

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        employee = _person(row.get('employee'))
        status, status_raw = normalize_status(row.get('status'))
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'dc_number': row.get('dc_number') or False,
            'employee_nopeg': employee.get('nopeg') or False,
            'employee_name': employee.get('name') or False,
            'location_name': _named(row.get('location')).get('name') or False,
            # Id lokasinya dipakai untuk menurunkan cabang. Namanya tidak
            # dipakai untuk itu: nama bisa berubah, id tidak.
            'location_id': _named(row.get('location')).get('id') or 0,
            'certificate_date': parse_date(row.get('certificate_date')),
            'start_date': parse_date(row.get('start_date')),
            'end_date': parse_date(row.get('end_date')),
            'reason': row.get('reason') or False,
            'file_path': row.get('certificate_file') or False,
            'status': status,
            'status_raw': status_raw,
            'approver_name': _person(row.get('approver')).get('name') or False,
            'approved_at': parse_datetime(row.get('approved_at')),
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
            **approval_summary_values(row),
            'approval_step_ids': approval_step_commands(row),
        }


class PresenlySaasAttendanceCorrection(models.Model):
    """Cermin `GET /v1/attendance-corrections` — permintaan koreksi presensi."""

    _name = 'presenly.saas.attendance.correction'
    _inherit = ['presenly.saas.mirror.mixin', 'presenly.saas.submission.mixin']
    _description = 'Presenly Attendance Correction (mirror)'
    _order = ORDER_PENGAJUAN

    _mirror_resource = 'attendance-corrections'
    _mirror_date_field = 'date'

    employee_nopeg = fields.Char(string='Nopeg', index=True)
    employee_name = fields.Char(string='Employee', index=True)

    date = fields.Date(string='Attendance Date', index=True)
    requested_check_in_time = fields.Datetime(string='Requested Check-in')
    requested_check_out_time = fields.Datetime(string='Requested Check-out')
    original_check_in_time = fields.Datetime(string='Recorded Check-in')
    original_check_out_time = fields.Datetime(string='Recorded Check-out')
    shift_name = fields.Char(string='Requested Shift')
    original_shift_name = fields.Char(string='Recorded Shift')
    reason = fields.Text(string='Reason')

    tl_approver_name = fields.Char(string='Team Lead Approver')
    # Waktu keputusan tiap level ikut dicatat server, dan justru itu yang membuat
    # riwayatnya terbaca: siapa memutuskan apa, dan kapan. Sebelum ini hanya nama
    # penyetujunya yang dicerminkan, sehingga urutannya tidak bisa dipastikan.
    tl_approved_at = fields.Datetime(string='Team Lead Approved At')
    manager_approver_name = fields.Char(string='Manager Approver')
    manager_approved_at = fields.Datetime(string='Manager Approved At')
    rejecter_name = fields.Char(string='Rejected By')
    rejected_at = fields.Datetime(string='Rejected At')
    rejection_reason = fields.Text(string='Rejection Reason')

    approval_step_ids = fields.One2many(
        'presenly.saas.approval.step.attendance.correction', 'correction_id',
        string='Approval Steps',
    )

    @api.depends('employee_name', 'date')
    def _compute_display_name(self):
        for correction in self:
            correction.display_name = '%s — %s' % (
                correction.employee_name or 'Koreksi', correction.date or '',
            )

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        employee = _person(row.get('employee'))
        status, status_raw = normalize_status(row.get('status'))
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'employee_nopeg': employee.get('nopeg') or False,
            'employee_name': employee.get('name') or False,
            'date': parse_date(row.get('date')),
            'requested_check_in_time': parse_datetime(row.get('requested_check_in_time')),
            'requested_check_out_time': parse_datetime(row.get('requested_check_out_time')),
            'original_check_in_time': parse_datetime(row.get('original_check_in_time')),
            'original_check_out_time': parse_datetime(row.get('original_check_out_time')),
            'shift_name': _named(row.get('shift')).get('name') or False,
            'original_shift_name': _named(row.get('original_shift')).get('name') or False,
            'reason': row.get('reason') or False,
            'status': status,
            'status_raw': status_raw,
            'tl_approver_name': _person(row.get('tl_approver')).get('name') or False,
            'tl_approved_at': parse_datetime(row.get('tl_approved_at')),
            'manager_approver_name': _person(row.get('manager_approver')).get('name') or False,
            'manager_approved_at': parse_datetime(row.get('manager_approved_at')),
            'rejecter_name': _person(row.get('rejecter')).get('name') or False,
            'rejected_at': parse_datetime(row.get('rejected_at')),
            'rejection_reason': row.get('rejection_reason') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
            **approval_summary_values(row),
            'approval_step_ids': approval_step_commands(row),
        }


class PresenlySaasShiftSwap(models.Model):
    """Cermin `GET /v1/shift-swaps` — permintaan tukar shift."""

    _name = 'presenly.saas.shift.swap'
    _inherit = ['presenly.saas.mirror.mixin', 'presenly.saas.submission.mixin']
    _description = 'Presenly Shift Swap (mirror)'
    _order = ORDER_PENGAJUAN

    _mirror_resource = 'shift-swaps'
    _mirror_date_field = 'requester_date'

    requester_nopeg = fields.Char(string='Requester Nopeg', index=True)
    requester_name = fields.Char(string='Requester', index=True)
    target_nopeg = fields.Char(string='Counterpart Nopeg', index=True)
    target_name = fields.Char(string='Counterpart', index=True)

    requester_date = fields.Date(string='Requester Date', index=True)
    target_date = fields.Date(string='Counterpart Date')
    requester_shift_name = fields.Char(string='Requester Shift')
    target_shift_name = fields.Char(string='Counterpart Shift')
    reason = fields.Text(string='Reason')

    approver_name = fields.Char(string='Approver')
    approved_at = fields.Datetime(string='Approved At')
    rejecter_name = fields.Char(string='Rejected By')
    rejected_at = fields.Datetime(string='Rejected At')
    rejection_reason = fields.Text(string='Rejection Reason')

    approval_step_ids = fields.One2many(
        'presenly.saas.approval.step.shift.swap', 'swap_id', string='Approval Steps',
    )

    @api.depends('requester_name', 'requester_date', 'target_name')
    def _compute_display_name(self):
        for swap in self:
            swap.display_name = '%s → %s (%s)' % (
                swap.requester_name or 'Requester', swap.target_name or '?',
                swap.requester_date or '',
            )

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        requester = _person(row.get('requester'))
        target = _person(row.get('target'))
        status, status_raw = normalize_status(row.get('status'))
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'requester_nopeg': requester.get('nopeg') or False,
            'requester_name': requester.get('name') or False,
            'target_nopeg': target.get('nopeg') or False,
            'target_name': target.get('name') or False,
            'requester_date': parse_date(row.get('requester_date')),
            'target_date': parse_date(row.get('target_date')),
            'requester_shift_name': _named(row.get('requester_shift')).get('name') or False,
            'target_shift_name': _named(row.get('target_shift')).get('name') or False,
            'reason': row.get('reason') or False,
            'status': status,
            'status_raw': status_raw,
            'approver_name': _person(row.get('approver')).get('name') or False,
            'approved_at': parse_datetime(row.get('approved_at')),
            'rejecter_name': _person(row.get('rejecter')).get('name') or False,
            'rejected_at': parse_datetime(row.get('rejected_at')),
            'rejection_reason': row.get('rejection_reason') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
            **approval_summary_values(row),
            'approval_step_ids': approval_step_commands(row),
        }
