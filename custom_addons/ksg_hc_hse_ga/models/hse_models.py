from odoo import models, fields, api, _
from datetime import timedelta

class KsgHseSafetyInduction(models.Model):
    _name = 'ksg.hse.safety.induction'
    _description = 'Gate Safety Induction & Working Permit'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Dokumen HSE', default=lambda self: _('New'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek Lapangan Terkait', required=True)
    is_proyek_lapangan = fields.Boolean(string='Proyek Lapangan', default=True)
    safety_induction_ready = fields.Boolean(string='Safety Induction & Permit Ready', default=False, tracking=True)
    dokumen_permit = fields.Binary(string='Berkas Working Permit (SIO/K3)')
    filename_permit = fields.Char(string='Nama File')
    catatan = fields.Text(string='Catatan Keselamatan HSE')

    def action_verify_gate(self):
        self.write({'safety_induction_ready': True})


class KsgHseManpowerHours(models.Model):
    _name = 'ksg.hse.manpower.hours'
    _description = 'Agregasi Manpower Effective Hours'

    name = fields.Char(string='Periode Agregasi', required=True)
    cakupan_tenaga_kerja = fields.Selection([
        ('proyek', 'Tenaga Kerja Proyek'),
        ('internal', 'Engineering & Internal Kantor'),
        ('seluruh', 'Seluruh Tenaga Kerja Perusahaan')
    ], string='Cakupan', default='seluruh')
    total_jam_kerja = fields.Float(string='Total Jam Kerja Efektif (Hours)', default=0.0)
    jumlah_tenaga_kerja = fields.Integer(string='Jumlah Tenaga Kerja Terlibat', default=0)
    periode_bulan = fields.Selection([
        ('01', 'Januari'), ('02', 'Februari'), ('03', 'Maret'), ('04', 'April'),
        ('05', 'Mei'), ('06', 'Juni'), ('07', 'Juli'), ('08', 'Agustus'),
        ('09', 'September'), ('10', 'Oktober'), ('11', 'November'), ('12', 'Desember')
    ], string='Bulan', default='09')
    tahun = fields.Char(string='Tahun', default='2026')


class KsgHseAccidentReport(models.Model):
    _name = 'ksg.hse.accident.report'
    _description = 'e-Form Kecelakaan Kerja (KK1 / KK2)'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nomor Laporan KK', default=lambda self: _('Draft KK'))
    jenis_form = fields.Selection([
        ('kk1', 'Tahap 1 (KK1 - Laporan Kecelakaan)'),
        ('kk2', 'Tahap 2 (KK2 - Surat Keterangan Dokter)')
    ], default='kk1', required=True)
    worker_id = fields.Many2one('ksg.sales.worker', string='Korban / Pekerja', required=True)
    project_id = fields.Many2one('ksg.sales.project', string='Proyek / Lokasi Kerja')
    tanggal_kejadian = fields.Datetime(string='Waktu Kejadian', default=fields.Datetime.now, required=True)
    tanggal_kembali_kerja = fields.Date(string='Tanggal Sembuh / Kembali Kerja')
    lost_time_hours = fields.Float(string='Lost Time Hours', compute='_compute_lost_time', store=True)
    deadline_2x24 = fields.Datetime(string='Batas Waktu Pelaporan (SLA 2x24 Jam)', compute='_compute_deadline', store=True)
    is_late = fields.Boolean(string='Terlambat (> 2x24 Jam)', compute='_compute_deadline', store=True)
    kronologi = fields.Text(string='Kronologi Kejadian')
    tingkat_keparahan = fields.Selection([
        ('ringan', 'Ringan (Pertolongan Pertama)'),
        ('sedang', 'Sedang (Rawat Medis)'),
        ('berat', 'Berat (Cacat / Lost Time Injury)'),
        ('fatality', 'Fatality (Meninggal Dunia)')
    ], string='Tingkat Keparahan', default='ringan')
    status_klaim_bpjs = fields.Selection([
        ('draft', 'Draft'),
        ('diajukan', 'Diajukan ke BPJS'),
        ('diverifikasi', 'Terverifikasi BPJS'),
        ('cair', 'Klaim Dicairkan')
    ], string='Status Klaim BPJS', default='draft', tracking=True)

    @api.depends('tanggal_kejadian')
    def _compute_deadline(self):
        for rec in self:
            if rec.tanggal_kejadian:
                rec.deadline_2x24 = rec.tanggal_kejadian + timedelta(hours=48)
                rec.is_late = fields.Datetime.now() > rec.deadline_2x24
            else:
                rec.deadline_2x24 = False
                rec.is_late = False

    @api.depends('tanggal_kejadian', 'tanggal_kembali_kerja')
    def _compute_lost_time(self):
        for rec in self:
            if rec.tanggal_kejadian and rec.tanggal_kembali_kerja:
                d1 = rec.tanggal_kejadian.date()
                d2 = rec.tanggal_kembali_kerja
                days = (d2 - d1).days
                rec.lost_time_hours = max(days * 8.0, 0.0)
            else:
                rec.lost_time_hours = 0.0