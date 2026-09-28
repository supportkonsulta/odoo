from odoo import models, fields, api, _

class KsgOperationalAttendanceReport(models.Model):
    _name = 'ksg.operational.attendance.report'
    _description = 'Laporan Presensi Lapangan'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Laporan', required=True, copy=False, default=lambda self: _('New'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    periode_bulan = fields.Selection([
        ('01', 'Januari'), ('02', 'Februari'), ('03', 'Maret'), ('04', 'April'),
        ('05', 'Mei'), ('06', 'Juni'), ('07', 'Juli'), ('08', 'Agustus'),
        ('09', 'September'), ('10', 'Oktober'), ('11', 'November'), ('12', 'Desember')
    ], string='Bulan', required=True, default='01')
    tahun = fields.Char(string='Tahun', default='2026', required=True)
    file_presensi = fields.Binary(string='File Presensi (SIDAC / Presenly / Excel)')
    filename = fields.Char(string='Nama File')
    state = fields.Selection([
        ('draft', 'Draft Unggahan'),
        ('verified', 'Terverifikasi (Siap Tagih)')
    ], string='Status', default='draft', tracking=True)
    catatan = fields.Text(string='Catatan Presensi')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) in [_('New'), 'New', False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.attendance') or _('New')
        return super().create(vals_list)

    def action_verify(self):
        self.ensure_one()
        self.write({'state': 'verified'})
        if self.project_id:
            self.project_id.bapbast_ops_ready = True