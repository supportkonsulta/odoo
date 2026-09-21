from odoo import models, fields, api, _
from odoo.exceptions import UserError

class KsgOperationalAttendanceReport(models.Model):
    _name = 'ksg.operational.attendance.report'
    _description = 'Rekap Presensi Lapangan (SIDAC / Presenly)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tanggal_upload desc, id desc'

    name = fields.Char(string='Nomor Rekap', required=True, copy=False, default=lambda self: _('New'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    sumber_aplikasi = fields.Selection([
        ('presenly', 'Presenly Mobile App'),
        ('sidac', 'SIDAC Online Report'),
        ('manual', 'Rekap Fingerprint / Manual')
    ], string='Sumber Presensi', required=True, default='presenly', tracking=True)

    periode_bulan = fields.Selection([
        ('01', 'Januari'), ('02', 'Februari'), ('03', 'Maret'),
        ('04', 'April'), ('05', 'Mei'), ('06', 'Juni'),
        ('07', 'Juli'), ('08', 'Agustus'), ('09', 'September'),
        ('10', 'Oktober'), ('11', 'November'), ('12', 'Desember'),
    ], string='Bulan', required=True, default=lambda self: fields.Date.today().strftime('%m'), tracking=True)
    periode_tahun = fields.Char(string='Tahun', required=True, default=lambda self: fields.Date.today().strftime('%Y'), tracking=True)
    tanggal_upload = fields.Date(string='Tanggal Upload', default=fields.Date.context_today, readonly=True)

    file_laporan = fields.Binary(string='File Report Presensi', required=True)
    file_name = fields.Char(string='Nama File')
    uploaded_by = fields.Many2one('res.users', string='Diupload Oleh', default=lambda self: self.env.user, readonly=True)

    total_pekerja_hadir = fields.Integer(string='Total Hari Kerja / Kehadiran', tracking=True)
    total_jam_lembur = fields.Float(string='Total Jam Lembur', tracking=True)
    catatan = fields.Text(string='Catatan Validasi')

    state = fields.Selection([
        ('draft', 'Draft (Baru Diupload)'),
        ('verified', 'Terverifikasi Operasional'),
        ('rejected', 'Ditolak / Perlu Revisi')
    ], string='Status', default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.attendance.report') or _('New')
        return super().create(vals_list)

    def action_verify(self):
        self.ensure_one()
        self.write({'state': 'verified'})
        # Sinkronkan otomatis ke Dokumen Tagihan Proyek
        self.env['ksg.operational.billing.document'].create({
            'project_id': self.project_id.id,
            'jenis_dokumen': 'presensi',
            'attachment_id': self.file_laporan,
            'file_name': self.file_name or f"Presensi_{self.project_id.name}_{self.periode_bulan}_{self.periode_tahun}.pdf",
            'uploaded_by': self.env.user.id,
        })
        self.message_post(body=_("Presensi berhasil diverifikasi dan disinkronkan ke Dokumen Penagihan Proyek."))

    def action_reject(self):
        self.ensure_one()
        if not self.catatan:
            raise UserError(_("Mohon isi alasan penolakan pada kolom Catatan."))
        self.write({'state': 'rejected'})
        self.message_post(body=_("Presensi ditolak: %s") % self.catatan)

    def action_reset_draft(self):
        self.ensure_one()
        self.write({'state': 'draft'})
