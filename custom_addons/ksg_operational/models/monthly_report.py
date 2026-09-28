from odoo import models, fields, api, _

class KsgOperationalMonthlyReport(models.Model):
    _name = 'ksg.operational.monthly.report'
    _description = 'Laporan Proyek Bulanan'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Laporan Bulanan', required=True, copy=False, default=lambda self: _('New'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    periode_bulan = fields.Selection([
        ('01', 'Januari'), ('02', 'Februari'), ('03', 'Maret'), ('04', 'April'),
        ('05', 'Mei'), ('06', 'Juni'), ('07', 'Juli'), ('08', 'Agustus'),
        ('09', 'September'), ('10', 'Oktober'), ('11', 'November'), ('12', 'Desember')
    ], string='Bulan Periode', required=True, default='01')
    tahun = fields.Char(string='Tahun', default='2026', required=True)
    progres_fisik = fields.Float(string='Progres Fisik (%)', default=0.0)
    pekerja_aktif_count = fields.Integer(string='Jumlah Pekerja Aktif', compute='_compute_pekerja_aktif', store=True)
    kendala = fields.Text(string='Kendala Lapangan')
    solusi = fields.Text(string='Tindakan / Solusi')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Diserahkan ke Manajemen'),
        ('approved', 'Disetujui')
    ], string='Status', default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) in [_('New'), 'New', False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.monthly.report') or _('New')
        return super().create(vals_list)

    @api.depends('project_id.assignment_ids.status')
    def _compute_pekerja_aktif(self):
        for rec in self:
            if rec.project_id:
                rec.pekerja_aktif_count = len(rec.project_id.assignment_ids.filtered(lambda a: a.status == 'active'))
            else:
                rec.pekerja_aktif_count = 0

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.write({'state': 'approved'})