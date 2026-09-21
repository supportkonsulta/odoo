"""Daily Report Line — detail pekerjaan per baris (FR-006, FR-007)."""

from odoo import models, fields


class KsgEngineeringDailyReportLine(models.Model):
    _name = 'ksg.engineering.daily.report.line'
    _description = 'Detail Pekerjaan Daily Report'

    report_id = fields.Many2one(
        'ksg.engineering.daily.report', string='Daily Report',
        required=True, ondelete='cascade', index=True)
    jam_mulai = fields.Float(string='Jam Mulai')
    jam_selesai = fields.Float(string='Jam Selesai')
    personel_ids = fields.Many2many(
        'res.users', string='Personel Terlibat')
    wbs_id = fields.Many2one(
        'ksg.engineering.wbs', string='Item WBS', required=True,
        ondelete='restrict')
    progress = fields.Float(
        string='Progress (%)', digits=(5, 2),
        help='Persentase progress untuk item WBS ini pada hari ini.')
    deskripsi = fields.Text(string='Deskripsi Pekerjaan')
    evidence_ids = fields.Many2many(
        'ir.attachment', string='Evidence / Bukti Foto',
        help='Upload foto/dokumen bukti pelaksanaan pekerjaan.')
