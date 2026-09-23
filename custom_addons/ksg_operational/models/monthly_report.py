from odoo import models, fields, api, _
from odoo.exceptions import UserError

class KsgOperationalMonthlyReport(models.Model):
    _name = 'ksg.operational.monthly.report'
    _description = 'Laporan Bulanan Operasional Proyek'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'periode_tahun desc, periode_bulan desc, id desc'

    name = fields.Char(string='Nomor Laporan', required=True, copy=False, default=lambda self: _('New'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    periode_bulan = fields.Selection([
        ('01', 'Januari'), ('02', 'Februari'), ('03', 'Maret'),
        ('04', 'April'), ('05', 'Mei'), ('06', 'Juni'),
        ('07', 'Juli'), ('08', 'Agustus'), ('09', 'September'),
        ('10', 'Oktober'), ('11', 'November'), ('12', 'Desember'),
    ], string='Bulan', required=True, default=lambda self: fields.Date.today().strftime('%m'), tracking=True)
    periode_tahun = fields.Char(string='Tahun', required=True, default=lambda self: fields.Date.today().strftime('%Y'), tracking=True)
    author_id = fields.Many2one('res.users', string='Disusun Oleh', default=lambda self: self.env.user, readonly=True)

    pekerja_aktif_count = fields.Integer(string='Jumlah Pekerja Aktif', compute='_compute_pekerja_aktif', store=True)
    progres_pekerjaan = fields.Float(string='Progres Fisik Proyek (%)', tracking=True)
    
    ringkasan_aktivitas = fields.Html(string='Ringkasan Aktivitas Lapangan')
    kendala_lapangan = fields.Text(string='Kendala & Hambatan')
    solusi_tindakan = fields.Text(string='Tindakan / Solusi Penanganan')

    file_lampiran = fields.Binary(string='File Laporan / Foto Dokumentasi')
    file_name = fields.Char(string='Nama File')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Diserahkan ke Manajemen'),
        ('approved', 'Disetujui Manajemen')
    ], string='Status', default='draft', tracking=True)

    @api.depends('project_id', 'project_id.assignment_ids.status_aktif')
    def _compute_pekerja_aktif(self):
        for rec in self:
            if rec.project_id:
                rec.pekerja_aktif_count = len(rec.project_id.assignment_ids.filtered(lambda a: a.status_aktif))
            else:
                rec.pekerja_aktif_count = 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.monthly.report') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        self.ensure_one()
        if not self.ringkasan_aktivitas:
            raise UserError(_("Ringkasan aktivitas lapangan wajib diisi."))
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.ensure_one()
        self.write({'state': 'approved'})
        self.message_post(body=_("Laporan bulanan telah disetujui manajemen."))

    def action_reset_draft(self):
        self.ensure_one()
        self.write({'state': 'draft'})
