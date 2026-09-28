"""WBS — Work Breakdown Structure (FR-003, FR-004, FR-004A, FR-005, FR-010).

Hierarkis: parent_id/child_ids (self-referencing).
Bobot = nilai_pekerjaan / nilai_kontrak_terkini × 100.
Planned/Actual progress per minggu & kumulatif.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class KsgEngineeringWbsTarget(models.Model):
    _name = 'ksg.engineering.wbs.target'
    _description = 'Target Mingguan WBS'
    _order = 'periode_minggu_id'

    wbs_id = fields.Many2one('ksg.engineering.wbs', string='WBS', required=True, ondelete='cascade')
    periode_minggu_id = fields.Many2one('ksg.engineering.schedule.week', string='Minggu', required=True, ondelete='restrict')
    target_progress = fields.Float(string='Target Progres (%)', digits=(5, 2), required=True, default=0.0)

    _sql_constraints = [
        ('wbs_minggu_unik', 'unique(wbs_id, periode_minggu_id)', 'Setiap WBS hanya boleh memiliki satu target per minggu.')
    ]


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

    # Mode Distribusi & Target (S-Curve Parity)
    mode_distribusi = fields.Selection([
        ('otomatis', 'Dibagi Rata (Otomatis)'),
        ('manual', 'Manual (Sesuai Excel)')
    ], string='Mode Distribusi Progres', default='otomatis', required=True, tracking=True)

    target_ids = fields.One2many(
        'ksg.engineering.wbs.target', 'wbs_id', string='Target Per Minggu')

    # Progress (FR-004, FR-010)
    planned_progress_kumulatif = fields.Float(
        string='Planned Progress Kumulatif (%)',
        compute='_compute_planned', store=True, digits=(5, 2))
    actual_progress_kumulatif = fields.Float(
        string='Actual Progress Kumulatif (%)',
        compute='_compute_actual', digits=(5, 2))

    # Backward compatibility helper for reports
    periode_minggu_ids = fields.Many2many(
        'ksg.engineering.schedule.week', compute='_compute_periode_minggu_ids', store=True)

    @api.depends('target_ids.periode_minggu_id')
    def _compute_periode_minggu_ids(self):
        for rec in self:
            rec.periode_minggu_ids = [(6, 0, rec.target_ids.mapped('periode_minggu_id').ids)]

    # Otorisasi luar periode (FR-004A)
    otorisasi_luar_periode = fields.Boolean(
        string='Otorisasi Luar Periode')
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
    # COMPUTES & OVERRIDES
    # ==================================================================
    
    @api.depends('nama_pekerjaan', 'parent_id', 'parent_path')
    def _compute_display_name(self):
        for rec in self:
            if rec.parent_path:
                level = len(rec.parent_path.strip('/').split('/')) - 1
                indent = "   " * level
                rec.display_name = f"{indent}└ {rec.nama_pekerjaan}" if level > 0 else rec.nama_pekerjaan
            else:
                rec.display_name = rec.nama_pekerjaan

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

    @api.depends('target_ids.target_progress')
    def _compute_planned(self):
        """Hitung planned progress kumulatif berdasarkan tabel target."""
        for rec in self:
            rec.planned_progress_kumulatif = sum(rec.target_ids.mapped('target_progress'))

    @api.onchange('tanggal_mulai', 'tanggal_selesai', 'mode_distribusi', 'bobot')
    def _onchange_generate_targets(self):
        """Otomatis generate target mingguan jika mode=otomatis."""
        if self.mode_distribusi != 'otomatis' or not self.tanggal_mulai or not self.tanggal_selesai or not self.project_id:
            return
            
        weeks = self.project_id.schedule_week_ids.filtered(
            lambda w: (w.tanggal_mulai <= self.tanggal_selesai and w.tanggal_selesai >= self.tanggal_mulai)
        )
        
        target_cmds = [(5, 0, 0)] # Clear existing
        n_weeks = len(weeks)
        if n_weeks and self.bobot:
            progress_per_week = self.bobot / n_weeks
            for w in weeks:
                target_cmds.append((0, 0, {
                    'periode_minggu_id': w.id,
                    'target_progress': progress_per_week
                }))
        
        self.target_ids = target_cmds

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
