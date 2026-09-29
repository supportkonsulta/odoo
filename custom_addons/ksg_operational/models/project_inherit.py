from odoo import models, fields, api

class KsgSalesProjectInherit(models.Model):
    _inherit = 'ksg.sales.project'

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
    bast_ids = fields.One2many(
        'ksg.operational.bast', 
        'project_id', 
        string='Daftar BAST'
    )
    work_report_ids = fields.One2many(
        'ksg.operational.work.report', 
        'project_id', 
        string='Laporan Pekerjaan'
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

    @api.depends('kode_proyek')
    def _compute_display_name(self):
        for rec in self:
            code = rec.kode_proyek or ''
            name = ''
            for f in ['nama_pekerjaan', 'nama_proyek', 'name', 'deskripsi_pekerjaan', 'judul_proyek']:
                val = getattr(rec, f, False)
                if val and str(val).strip() and str(val).strip() != str(code).strip():
                    name = str(val).strip()
                    break
            if code and name:
                rec.display_name = f"{code} ({name})"
            elif code:
                rec.display_name = code
            elif name:
                rec.display_name = name
            else:
                rec.display_name = f"Proyek #{rec.id}"