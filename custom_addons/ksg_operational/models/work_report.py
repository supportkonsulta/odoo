from odoo import models, fields, api, _

class KsgOperationalWorkReport(models.Model):
    _name = 'ksg.operational.work.report'
    _description = 'Laporan Bulanan Pekerjaan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tanggal_laporan desc, id desc'

    name = fields.Char(string='Nomor Dokumen Laporan', required=True, copy=False, default=lambda self: _('Draft Laporan'))
    project_id = fields.Many2one('ksg.sales.project', string='Pekerjaan / Proyek', required=True, tracking=True)
    tanggal_laporan = fields.Date(string='Tanggal Laporan', default=fields.Date.context_today)

    pekerjaan = fields.Char(string='Pekerjaan', compute='_compute_project_details', store=True, readonly=False)
    kontraktor = fields.Char(string='Kontraktor', default='PT KONSULTA SEMEN GRESIK')
    no_pekerjaan = fields.Char(string='Nomor SPK / Dokumen', compute='_compute_project_details', store=True, readonly=False)

    bulan = fields.Selection([
        ('01', 'Januari'), ('02', 'Februari'), ('03', 'Maret'),
        ('04', 'April'), ('05', 'Mei'), ('06', 'Juni'),
        ('07', 'Juli'), ('08', 'Agustus'), ('09', 'September'),
        ('10', 'Oktober'), ('11', 'November'), ('12', 'Desember')
    ], string='Bulan', required=True, default='07', tracking=True)
    tahun = fields.Char(string='Tahun', default='2026', required=True)

    line_ids = fields.One2many('ksg.operational.work.report.line', 'laporan_id', string='Detail Pekerjaan')
    catatan = fields.Text(string='Catatan Tambahan')

    state = fields.Selection([
        ('draft', 'Draft Laporan'),
        ('submitted', 'Diserahkan ke Manajemen'),
        ('approved', 'Disetujui')
    ], string='Status', default='draft', tracking=True)

    @api.depends('project_id')
    def _compute_project_details(self):
        for rec in self:
            if rec.project_id:
                p_name = getattr(rec.project_id, 'nama_pekerjaan', False) or getattr(rec.project_id, 'display_name', '')
                rec.pekerjaan = p_name
                spk = getattr(rec.project_id, 'nomor_spk', False) or getattr(rec.project_id, 'kode_proyek', '')
                rec.no_pekerjaan = spk
            else:
                if not rec.pekerjaan:
                    rec.pekerjaan = ''
                if not rec.no_pekerjaan:
                    rec.no_pekerjaan = ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Draft Laporan')) in [_('Draft Laporan'), 'Draft Laporan', False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.work.report') or _('Draft Laporan')
        return super().create(vals_list)

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_print_report(self):
        self.ensure_one()
        return self.env.ref('ksg_operational.action_report_laporan_pekerjaan').report_action(self)


class KsgOperationalWorkReportLine(models.Model):
    _name = 'ksg.operational.work.report.line'
    _description = 'Rincian Kegiatan Mingguan (Before-Progress-After)'
    _order = 'minggu_ke asc, tanggal asc, id asc'

    laporan_id = fields.Many2one('ksg.operational.work.report', string='Laporan', ondelete='cascade')
    minggu_ke = fields.Selection([
        ('1', 'Minggu 1'),
        ('2', 'Minggu 2'),
        ('3', 'Minggu 3'),
        ('4', 'Minggu 4')
    ], string='Minggu Ke', required=True, default='1')

    tanggal = fields.Date(string='Tanggal', default=fields.Date.context_today, required=True)
    deskripsi = fields.Char(string='Aktivitas / Uraian Pekerjaan', placeholder='Contoh: Pembersihan Kaca, Scrubbing Lantai')

    foto_before = fields.Binary(string='Foto Before', attachment=True)
    foto_progress = fields.Binary(string='Foto Progress', attachment=True)
    foto_after = fields.Binary(string='Foto After', attachment=True)