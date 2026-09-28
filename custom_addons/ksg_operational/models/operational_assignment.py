from odoo import models, fields, api, _

class KsgOperationalAssignment(models.Model):
    _name = 'ksg.operational.assignment'
    _description = 'Penugasan Tenaga Kerja Proyek'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='ID Penugasan', required=True, copy=False, default=lambda self: _('New'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    worker_name = fields.Char(string='Nama Pekerja', required=True, tracking=True)
    jabatan = fields.Char(string='Jabatan / Posisi', required=True)
    tanggal_mulai = fields.Date(string='Tanggal Mulai', default=fields.Date.context_today)
    tanggal_selesai = fields.Date(string='Tanggal Selesai')
    status = fields.Selection([
        ('active', 'Aktif'),
        ('ended', 'Selesai'),
        ('mutated', 'Mutasi')
    ], string='Status Penugasan', default='active', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) in [_('New'), 'New', False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.assignment') or _('New')
        return super().create(vals_list)

    @api.model
    def cron_check_assignment_status(self):
        today = fields.Date.context_today(self)
        expired = self.search([('status', '=', 'active'), ('tanggal_selesai', '<', today)])
        expired.write({'status': 'ended'})