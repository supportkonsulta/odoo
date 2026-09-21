"""WBS — Work Breakdown Structure (FR-003, FR-004, FR-004A, FR-005, FR-010).

Hierarkis: parent_id/child_ids (self-referencing).
Bobot = nilai_pekerjaan / nilai_kontrak_terkini × 100.
Planned/Actual progress per minggu & kumulatif.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class KsgEngineeringWbs(models.Model):
    _name = 'ksg.engineering.wbs'
    _description = 'WBS Engineering'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'project_id, parent_id, id'
    _parent_name = 'parent_id'
    _parent_store = True

    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='cascade', index=True, tracking=True)
    parent_id = fields.Many2one(
        'ksg.engineering.wbs', string='Parent WBS',
        ondelete='cascade', index=True)
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        'ksg.engineering.wbs', 'parent_id', string='Sub-Pekerjaan')

    nama_pekerjaan = fields.Char(
        string='Nama Pekerjaan', required=True, tracking=True)
    nilai_pekerjaan = fields.Monetary(
        string='Nilai Pekerjaan', required=True,
        currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(
        related='project_id.currency_id', store=True, readonly=True)

    volume = fields.Float(string='Volume')
    satuan = fields.Char(string='Satuan')
    durasi = fields.Integer(string='Durasi (hari)')
    tanggal_mulai = fields.Date(
        string='Tanggal Mulai', required=True, tracking=True)
    tanggal_selesai = fields.Date(
        string='Tanggal Selesai', required=True, tracking=True)

    # Bobot (FR-005, RULE-04)
    bobot = fields.Float(
        string='Bobot (%)', compute='_compute_bobot',
        store=True, digits=(5, 2), tracking=True)

    # Periode minggu (FR-004)
    periode_minggu_ids = fields.Many2many(
        'ksg.engineering.schedule.week', string='Periode Minggu')

    # Progress (FR-004, FR-010)
    planned_progress_mingguan = fields.Float(
        string='Planned Progress Mingguan (%)',
        compute='_compute_planned', store=True, digits=(5, 2))
    planned_progress_kumulatif = fields.Float(
        string='Planned Progress Kumulatif (%)',
        compute='_compute_planned', store=True, digits=(5, 2))
    actual_progress_kumulatif = fields.Float(
        string='Actual Progress Kumulatif (%)',
        compute='_compute_actual', digits=(5, 2))

    # Otorisasi luar periode (FR-004A)
    otorisasi_luar_periode = fields.Boolean(
        string='Otorisasi Luar Periode',
        groups='ksg_engineering.group_kepala_unit')
    alasan_luar_periode = fields.Text(string='Alasan Luar Periode')

    # ==================================================================
    # CONSTRAINTS
    # ==================================================================

    @api.constrains('tanggal_mulai', 'tanggal_selesai', 'project_id',
                    'otorisasi_luar_periode')
    def _check_periode(self):
        """RULE-03: WBS harus dalam periode kontrak project,
        kecuali ada otorisasi luar periode."""
        for rec in self:
            if rec.otorisasi_luar_periode:
                if not rec.alasan_luar_periode:
                    raise ValidationError(
                        'Otorisasi luar periode membutuhkan alasan.')
                continue
            project = rec.project_id
            if project.awal_kontrak and rec.tanggal_mulai:
                if rec.tanggal_mulai < project.awal_kontrak:
                    raise ValidationError(
                        f'Tanggal mulai WBS ({rec.tanggal_mulai}) '
                        f'sebelum awal kontrak ({project.awal_kontrak}). '
                        f'Gunakan otorisasi luar periode jika diperlukan.')
            if project.akhir_kontrak and rec.tanggal_selesai:
                if rec.tanggal_selesai > project.akhir_kontrak:
                    raise ValidationError(
                        f'Tanggal selesai WBS ({rec.tanggal_selesai}) '
                        f'setelah akhir kontrak ({project.akhir_kontrak}). '
                        f'Gunakan otorisasi luar periode jika diperlukan.')

    # ==================================================================
    # COMPUTES
    # ==================================================================

    @api.depends('nilai_pekerjaan', 'project_id.nilai_kontrak_terkini')
    def _compute_bobot(self):
        """RULE-04: bobot = nilai_pekerjaan / nilai_kontrak_terkini × 100.
        Recompute otomatis saat addendum (perubahan nilai_kontrak_terkini)."""
        for rec in self:
            nilai_kontrak = rec.project_id._get_nilai_kontrak()
            if nilai_kontrak:
                rec.bobot = (rec.nilai_pekerjaan / nilai_kontrak) * 100.0
            else:
                rec.bobot = 0.0

    @api.depends('bobot', 'periode_minggu_ids')
    def _compute_planned(self):
        """Distribusi bobot merata per minggu yang di-assign."""
        for rec in self:
            n_weeks = len(rec.periode_minggu_ids)
            if n_weeks and rec.bobot:
                rec.planned_progress_mingguan = rec.bobot / n_weeks
                rec.planned_progress_kumulatif = rec.bobot
            else:
                rec.planned_progress_mingguan = 0.0
                rec.planned_progress_kumulatif = 0.0

    def _compute_actual(self):
        """Actual progress dari daily report lines yang terkait WBS ini
        melalui konsolidasi approved.
        Non-stored karena bergantung pada search query lintas model."""
        DailyLine = self.env['ksg.engineering.daily.report.line']
        for rec in self:
            lines = DailyLine.search([
                ('wbs_id', '=', rec.id),
                ('report_id.state', '=', 'submitted'),
            ])
            total_actual = sum(lines.mapped('progress'))
            rec.actual_progress_kumulatif = min(total_actual, 100.0)
