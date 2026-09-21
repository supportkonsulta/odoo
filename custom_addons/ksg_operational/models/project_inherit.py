from odoo import models, fields, api

class KsgSalesProject(models.Model):
    _inherit = 'ksg.sales.project'

    manpower_plan_ids = fields.One2many('ksg.operational.manpower.plan', 'project_id', string='Rencana Manpower')
    equipment_plan_ids = fields.One2many('ksg.operational.equipment.plan', 'project_id', string='Rencana Perlengkapan')
    material_plan_ids = fields.One2many('ksg.operational.material.plan', 'project_id', string='Rencana Alat & Bahan')
    manpower_request_ids = fields.One2many('ksg.operational.manpower.request', 'project_id', string='Permohonan Manpower')
    assignment_ids = fields.One2many('ksg.operational.assignment', 'project_id', string='Penugasan Tenaga Kerja')
    procurement_ids = fields.One2many('ksg.operational.procurement.request', 'project_id', string='Pengadaan Alat/Bahan')
    billing_document_ids = fields.One2many('ksg.operational.billing.document', 'project_id', string='Dokumen Penagihan')

    total_biaya_operasional_plan = fields.Monetary(
        string='Total Estimasi Biaya Rencana', 
        compute='_compute_total_biaya_plan', 
        store=True,
        currency_field='currency_id'
    )
    bapbast_ops_ready = fields.Boolean(
        string='Dokumen Ops Siap Tagih', 
        compute='_compute_bapbast_ops_ready', 
        store=True
    )

    @api.depends('manpower_plan_ids.total_biaya', 'equipment_plan_ids.total_biaya')
    def _compute_total_biaya_plan(self):
        for rec in self:
            mp_total = sum(rec.manpower_plan_ids.mapped('total_biaya'))
            eq_total = sum(rec.equipment_plan_ids.mapped('total_biaya'))
            rec.total_biaya_operasional_plan = mp_total + eq_total

    @api.depends('billing_document_ids.attachment_id')
    def _compute_bapbast_ops_ready(self):
        for rec in self:
            # Minimal terdapat dokumen Presensi dan Laporan Pekerjaan/BAST yang sudah terupload
            docs = rec.billing_document_ids.filtered(lambda d: d.attachment_id)
            jenis_terpenuhi = docs.mapped('jenis_dokumen')
            rec.bapbast_ops_ready = ('presensi' in jenis_terpenuhi and ('bast' in jenis_terpenuhi or 'laporan_pekerjaan' in jenis_terpenuhi))