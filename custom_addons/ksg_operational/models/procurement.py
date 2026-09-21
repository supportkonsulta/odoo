from odoo import models, fields, api, _
from odoo.exceptions import UserError

class KsgOperationalProcurementRequest(models.Model):
    _name = 'ksg.operational.procurement.request'
    _description = 'Pengajuan Pengadaan Alat dan Bahan (BoQ)'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Pengadaan', required=True, copy=False, default=lambda self: _('New'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    requested_by = fields.Many2one('res.users', string='Diajukan Oleh', default=lambda self: self.env.user)
    boq_line_ids = fields.One2many('ksg.operational.boq.line', 'procurement_id', string='Rincian BoQ')
    catatan_penolakan = fields.Text(string='Alasan Penolakan')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_approval', 'Menunggu Approval Direktur'),
        ('approved', 'Disetujui'),
        ('rejected', 'Ditolak')
    ], string='Status', default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq = self.env['ir.sequence'].next_by_code('ksg.operational.procurement')
                if seq:
                    vals['name'] = seq
                else:
                    proj_id = vals.get('project_id')
                    proj_name = self.env['ksg.sales.project'].browse(proj_id).name if proj_id else ''
                    vals['name'] = f"BOQ/{proj_name}" if proj_name else 'BOQ/DRAFT'
        return super().create(vals_list)

    def action_submit(self):
        self.ensure_one()
        if not self.boq_line_ids:
            raise UserError(_("Rincian barang pada BoQ tidak boleh kosong!"))
        self.write({'state': 'waiting_approval'})

    def action_approve(self):
        self.ensure_one()
        self.write({'state': 'approved'})
        self.message_post(body=_("Pengadaan barang telah disetujui Direktur."))

    def action_reject(self):
        self.ensure_one()
        if not self.catatan_penolakan:
            raise UserError(_("Wajib mengisi alasan penolakan!"))
        self.write({'state': 'rejected'})


class KsgOperationalBoqLine(models.Model):
    _name = 'ksg.operational.boq.line'
    _description = 'Item Bill of Quantity (BoQ)'

    procurement_id = fields.Many2one('ksg.operational.procurement.request', string='Pengadaan', required=True, ondelete='cascade')
    item = fields.Char(string='Nama Barang / Alat', required=True)
    spesifikasi = fields.Char(string='Spesifikasi')
    satuan = fields.Char(string='Satuan', required=True, default='Unit')
    jumlah = fields.Float(string='Jumlah', required=True, default=1.0)