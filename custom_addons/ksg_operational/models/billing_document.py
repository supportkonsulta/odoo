from odoo import models, fields

class KsgOperationalBillingDocument(models.Model):
    _name = 'ksg.operational.billing.document'
    _description = 'Dokumen Pendukung Penagihan Proyek'

    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, ondelete='cascade')
    jenis_dokumen = fields.Selection([
        ('presensi', 'Laporan Presensi (SIDAC/Presenly)'),
        ('laporan_pekerjaan', 'Laporan Pekerjaan Lapangan'),
        ('bast', 'BAST / Berita Acara'),
        ('lainnya', 'Dokumen Khusus Client')
    ], string='Jenis Dokumen', required=True)
    attachment_id = fields.Binary(string='File Dokumen Lampiran', required=True)
    file_name = fields.Char(string='Nama File')
    uploaded_by = fields.Many2one('res.users', string='Diupload Oleh', default=lambda self: self.env.user)