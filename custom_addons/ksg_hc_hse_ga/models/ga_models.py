from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class KsgGaRequest(models.Model):
    _name = 'ksg.ga.request'
    _description = 'e-Form Ticketing General Affairs (GA)'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Tiket GA', default=lambda self: _('Draft Tiket'))
    jenis = fields.Selection([
        ('atk', 'ATK (Alat Tulis Kantor)'),
        ('bbm', 'BBM Kendaraan Dinas'),
        ('jamuan', 'Konsumsi & Jamuan Kantor'),
        ('maintenance', 'Pemeliharaan Gedung / Fasilitas'),
        ('facility', 'Peminjaman Fasilitas / Ruang'),
        ('hotel', 'Akomodasi Hotel Internal'),
        ('tiket', 'Tiket Transportasi Dinas'),
        ('ppl', 'Permintaan Pembayaran Langsung (PPL)')
    ], string='Kategori Kebutuhan', required=True, default='atk')
    requester_id = fields.Many2one('res.users', string='Pemohon', default=lambda self: self.env.user)
    deskripsi = fields.Text(string='Uraian Kebutuhan', required=True)
    nominal = fields.Monetary(string='Estimasi Nominal (Rp)', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    terkait_project_eksternal = fields.Boolean(string='Terkait Proyek Lapangan Eksternal', default=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('diajukan', 'Diajukan'),
        ('disetujui', 'Disetujui Kelayakan (ACC GA)'),
        ('ditolak', 'Ditolak'),
        ('selesai', 'Selesai')
    ], string='Status Kelayakan', default='draft', tracking=True)

    @api.constrains('terkait_project_eksternal')
    def _check_project_eksternal(self):
        for rec in self:
            if rec.terkait_project_eksternal:
                raise ValidationError(_("Kebutuhan Proyek Eksternal wajib diajukan melalui modul BoQ / Operasional, bukan GA."))

    def action_submit(self):
        self.write({'state': 'diajukan'})

    def action_approve(self):
        self.ensure_one()
        self.write({'state': 'disetujui'})
        if self.nominal > 0:
            self.env['ksg.ga.umo'].create({
                'request_id': self.id,
                'nominal': self.nominal,
                'state': 'diajukan'
            })


class KsgGaUmo(models.Model):
    _name = 'ksg.ga.umo'
    _description = 'Uang Muka Operasional (UMO) GA'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Pengajuan UMO', default=lambda self: _('Draft UMO'))
    request_id = fields.Many2one('ksg.ga.request', string='Tiket GA Terkait', required=True)
    nominal = fields.Monetary(string='Nominal Pencairan', currency_field='currency_id', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    state = fields.Selection([
        ('diajukan', 'Diajukan'),
        ('diproses_ga_keuangan', 'Diproses GA & Keuangan'),
        ('disetujui_direktur', 'Disetujui Direktur (ACC Pencairan)'),
        ('dicairkan', 'Sudah Dicairkan Keuangan'),
        ('ditolak', 'Ditolak')
    ], default='diajukan', tracking=True)

    def action_proses(self):
        self.write({'state': 'diproses_ga_keuangan'})

    def action_approve_direktur(self):
        self.write({'state': 'disetujui_direktur'})

    def action_cair(self):
        self.write({'state': 'dicairkan'})


class KsgGaCorrespondence(models.Model):
    _name = 'ksg.ga.correspondence'
    _description = 'Surat-Menyurat & Arsip Digital GA'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Surat Otomatis', copy=False, default=lambda self: _('New'))
    jenis = fields.Selection([
        ('surat_masuk', 'Surat Masuk'),
        ('surat_keluar', 'Surat Keluar'),
        ('spbd', 'SPBD (Surat Perintah Bongkar/Muat)'),
        ('offering_letter', 'Offering Letter'),
        ('pkwt', 'Perjanjian Kerja (PKWT/PKWTT)'),
        ('surat_keterangan_kerja', 'Surat Keterangan Kerja'),
        ('mou_b2b', 'MoU / PKS B2B')
    ], string='Jenis Surat / Dokumen', required=True, default='surat_keluar')
    pengelola = fields.Selection([('ga', 'General Affairs (GA)'), ('hc', 'Human Capital (HC)')], default='ga', required=True)
    akses_terbatas = fields.Boolean(string='Akses Terbatas / Dokumen Sensitif', compute='_compute_akses', store=True)
    tanggal = fields.Date(string='Tanggal Surat', default=fields.Date.context_today)
    perihal = fields.Char(string='Perihal / Judul Dokumen', required=True)
    file_dokumen = fields.Binary(string='Scan Dokumen / Berkas')
    filename = fields.Char(string='Nama File')

    @api.depends('jenis')
    def _compute_akses(self):
        for rec in self:
            rec.akses_terbatas = rec.jenis in ['pkwt', 'mou_b2b', 'spbd', 'offering_letter']