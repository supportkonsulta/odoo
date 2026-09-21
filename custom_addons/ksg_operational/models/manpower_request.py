from odoo import models, fields, _
from odoo.exceptions import UserError

class KsgOperationalManpowerRequest(models.Model):
    _name = 'ksg.operational.manpower.request'
    _description = 'Permohonan Kebutuhan Manpower ke HC'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    jumlah_dibutuhkan = fields.Integer(string='Jumlah Dibutuhkan', required=True, default=1, tracking=True)
    kriteria = fields.Char(string='Kriteria / Role', required=True, tracking=True)
    catatan = fields.Text(string='Catatan Kebutuhan')
    requested_by = fields.Many2one('res.users', string='Pemohon', default=lambda self: self.env.user, tracking=True)
    handled_by = fields.Many2one('res.users', string='Ditindaklanjuti Oleh HC', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Diajukan ke HC'),
        ('in_process', 'Sedang Diproses HC'),
        ('fulfilled', 'Terpenuhi'),
        ('rejected', 'Ditolak')
    ], string='Status', default='draft', tracking=True)

    def action_submit(self):
        self.ensure_one()
        self.write({'state': 'submitted'})
        self.message_post(body=_("Permohonan tenaga kerja diajukan ke HC."))

    def action_process(self):
        self.ensure_one()
        self.write({'state': 'in_process', 'handled_by': self.env.user.id})

    def action_fulfill(self):
        self.ensure_one()
        self.write({'state': 'fulfilled', 'handled_by': self.env.user.id})
        self.message_post(body=_("Permohonan tenaga kerja telah dipenuhi oleh HC."))

    def action_reject(self):
        self.ensure_one()
        if not self.catatan:
            raise UserError(_("Harap sertakan alasan penolakan pada kolom Catatan."))
        self.write({'state': 'rejected', 'handled_by': self.env.user.id})