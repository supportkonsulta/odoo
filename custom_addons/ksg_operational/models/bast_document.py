from odoo import models, fields, api, _

class KsgOperationalBast(models.Model):
    _name = 'ksg.operational.bast'
    _description = 'Berita Acara Serah Terima (BAST) Operasional'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tanggal_bast desc, id desc'

    name = fields.Char(string='Nomor BAST', required=True, copy=False, default=lambda self: _('Draft BAST'))
    project_id = fields.Many2one('ksg.sales.project', string='Pekerjaan / Proyek Terkait', required=True, tracking=True)
    tanggal_bast = fields.Date(string='Tanggal BAST', default=fields.Date.context_today, tracking=True)
    periode_bulan = fields.Selection([
        ('01', 'Januari'), ('02', 'Februari'), ('03', 'Maret'), ('04', 'April'),
        ('05', 'Mei'), ('06', 'Juni'), ('07', 'Juli'), ('08', 'Agustus'),
        ('09', 'September'), ('10', 'Oktober'), ('11', 'November'), ('12', 'Desember')
    ], string='Periode Bulan', required=True, default='01', tracking=True)
    tahun = fields.Char(string='Tahun', default='2026', required=True)

    pihak_pertama = fields.Char(string='Pihak Pertama (Klien / Pemberi Kerja)', placeholder='Contoh: RS Muhammadiyah Gresik')
    pihak_kedua = fields.Char(string='Pihak Kedua (Pelaksana)', default='PT KONSULTA SEMEN GRESIK')
    nomor_kontrak_spk = fields.Char(string='Nomor SPK / Kontrak', compute='_compute_spk', store=True, readonly=False)

    file_bast = fields.Binary(string='Scan Berkas BAST Bertandatangan')
    filename_bast = fields.Char(string='Nama File BAST')
    catatan = fields.Text(string='Catatan / Keterangan Serah Terima')

    state = fields.Selection([
        ('draft', 'Draft BAST'),
        ('verified', 'Sah / Terverifikasi')
    ], string='Status', default='draft', tracking=True)

    @api.depends('project_id')
    def _compute_spk(self):
        for rec in self:
            if rec.project_id:
                rec.nomor_kontrak_spk = getattr(rec.project_id, 'nomor_spk', False) or rec.project_id.kode_proyek or ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Draft BAST')) in [_('Draft BAST'), 'Draft BAST', False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.bast') or _('Draft BAST')
        return super().create(vals_list)

    def action_verify(self):
        self.ensure_one()
        self.write({'state': 'verified'})
        if self.project_id and hasattr(self.project_id, 'bapbast_ops_ready'):
            self.project_id.bapbast_ops_ready = True

    def action_reset_draft(self):
        self.write({'state': 'draft'})