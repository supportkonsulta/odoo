from odoo import models, fields

class KsgSalesProjectInherit(models.Model):
    _inherit = 'ksg.sales.project'

    # Relasi Operasional Eksisting (Dibutuhkan oleh Monthly Report & Penugasan)
    assignment_ids = fields.One2many(
        'ksg.operational.assignment', 
        'project_id', 
        string='Daftar Penugasan'
    )
    attendance_report_ids = fields.One2many(
        'ksg.operational.attendance.report', 
        'project_id', 
        string='Laporan Presensi'
    )
    monthly_report_ids = fields.One2many(
        'ksg.operational.monthly.report', 
        'project_id', 
        string='Laporan Bulanan'
    )
    billing_document_ids = fields.One2many(
        'ksg.operational.billing.document', 
        'project_id', 
        string='Dokumen Penagihan'
    )
    bapbast_ops_ready = fields.Boolean(
        string='Dokumen Ops Siap Tagih', 
        default=False
    )

    # Relasi Alur Baru: SDM, Perlengkapan & Lembar HPP
    manpower_request_ids = fields.One2many(
        'ksg.operational.manpower.request', 
        'project_id', 
        string='Permintaan SDM'
    )
    supply_request_ids = fields.One2many(
        'ksg.operational.supply.request', 
        'project_id', 
        string='Permintaan Perlengkapan'
    )
    hpp_ids = fields.One2many(
        'ksg.operational.hpp', 
        'project_id', 
        string='Lembar HPP Operasional'
    )