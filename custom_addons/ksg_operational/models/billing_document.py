from odoo import models, fields, api, _

class KsgOperationalBillingDocument(models.Model):
    _name = 'ksg.operational.billing.document'
    _description = 'Dokumen Penagihan Operasional'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Berkas Tagihan', required=True, copy=False, default=lambda self: _('New'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek Terkait', required=True, tracking=True)
    tanggal = fields.Date(string='Tanggal', default=fields.Date.context_today)
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)
    nominal = fields.Monetary(string='Nominal Tagihan', currency_field='currency_id')
    file_bap = fields.Binary(string='File BAP')
    filename_bap = fields.Char(string='Nama File BAP')
    file_bast = fields.Binary(string='File BAST')
    filename_bast = fields.Char(string='Nama File BAST')
    catatan = fields.Text(string='Catatan Penagihan')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Diserahkan ke Keuangan'),
        ('verified', 'Terverifikasi')
    ], string='Status', default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) in [_('New'), 'New', False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.billing') or _('New')
        return super().create(vals_list)