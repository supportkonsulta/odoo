from odoo import models, fields, api

class KsgOperationalManpowerPlan(models.Model):
    _name = 'ksg.operational.manpower.plan'
    _description = 'Rencana Kebutuhan Manpower Proyek'

    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, ondelete='cascade')
    currency_id = fields.Many2one('res.currency', related='project_id.currency_id')
    role = fields.Char(string='Peran / Posisi', required=True)
    jumlah = fields.Float(string='Jumlah Pekerja', required=True, default=1.0)
    estimasi_biaya_satuan = fields.Monetary(string='Estimasi Biaya / Orang (Inc. BPJS)', required=True)
    total_biaya = fields.Monetary(string='Total Biaya', compute='_compute_total_biaya', store=True)

    @api.depends('jumlah', 'estimasi_biaya_satuan')
    def _compute_total_biaya(self):
        for rec in self:
            rec.total_biaya = rec.jumlah * rec.estimasi_biaya_satuan


class KsgOperationalEquipmentPlan(models.Model):
    _name = 'ksg.operational.equipment.plan'
    _description = 'Rencana Perlengkapan Kerja Proyek'

    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, ondelete='cascade')
    currency_id = fields.Many2one('res.currency', related='project_id.currency_id')
    name = fields.Char(string='Perlengkapan (Seragam/Safety)', required=True)
    jumlah = fields.Float(string='Jumlah', required=True, default=1.0)
    estimasi_biaya_satuan = fields.Monetary(string='Estimasi Biaya Satuan', required=True)
    total_biaya = fields.Monetary(string='Total Biaya', compute='_compute_total_biaya', store=True)

    @api.depends('jumlah', 'estimasi_biaya_satuan')
    def _compute_total_biaya(self):
        for rec in self:
            rec.total_biaya = rec.jumlah * rec.estimasi_biaya_satuan


class KsgOperationalMaterialPlan(models.Model):
    _name = 'ksg.operational.material.plan'
    _description = 'Rencana Kebutuhan Alat dan Bahan'

    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, ondelete='cascade')
    name = fields.Char(string='Nama Alat / Bahan', required=True)
    spesifikasi = fields.Char(string='Spesifikasi')
    jumlah = fields.Float(string='Estimasi Kebutuhan', required=True, default=1.0)
    satuan = fields.Char(string='Satuan (Unit/Pcs/Mtr)', required=True)