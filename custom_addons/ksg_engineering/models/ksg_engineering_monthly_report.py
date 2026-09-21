"""Monthly Report Engineering (FR-009).

Agregasi dari weekly report per bulan.
Generated via ir.cron (RULE-06).
"""

from odoo import models, fields, api
from datetime import date


class KsgEngineeringMonthlyReport(models.Model):
    _name = 'ksg.engineering.monthly.report'
    _description = 'Laporan Bulanan Engineering'
    _inherit = ['mail.thread']
    _order = 'project_id, bulan desc, tahun desc'

    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='cascade', index=True, tracking=True)
    bulan = fields.Integer(string='Bulan', required=True)
    tahun = fields.Integer(string='Tahun', required=True)
    weekly_report_ids = fields.Many2many(
        'ksg.engineering.weekly.report', 
        relation='ksg_eng_monthly_weekly_rel',
        string='Laporan Mingguan Terkait')

    planned_progress = fields.Float(
        string='Planned Progress (%)', digits=(5, 2))
    actual_progress = fields.Float(
        string='Actual Progress (%)', digits=(5, 2),
        compute='_compute_progress', store=True)
    variance = fields.Float(
        string='Variance (%)', compute='_compute_variance',
        store=True, digits=(5, 2))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Selesai'),
    ], string='Status', default='draft', tracking=True, required=True)

    _unique_project_month = models.Constraint(
        'UNIQUE(project_id, bulan, tahun)',
        'Laporan bulanan harus unik per project per bulan.',
    )

    def _compute_display_name(self):
        for rec in self:
            project_name = rec.project_id.kode_proyek or ''
            rec.display_name = f"MR-{project_name}-{rec.tahun}/{rec.bulan:02d}"

    @api.depends('weekly_report_ids.actual_progress')
    def _compute_progress(self):
        for rec in self:
            rec.actual_progress = sum(
                rec.weekly_report_ids.mapped('actual_progress'))

    @api.depends('planned_progress', 'actual_progress')
    def _compute_variance(self):
        for rec in self:
            rec.variance = rec.actual_progress - rec.planned_progress

    # ==================================================================
    # CRON: Generate monthly (RULE-06)
    # ==================================================================

    @api.model
    def _cron_generate_monthly(self):
        """Cron bulanan: buat/update monthly report dari weekly."""
        today = date.today()
        # Proses bulan sebelumnya
        if today.month == 1:
            target_month = 12
            target_year = today.year - 1
        else:
            target_month = today.month - 1
            target_year = today.year

        projects = self.env['ksg.sales.project'].search([
            ('status', '=', 'aktif'),
        ])
        WeeklyReport = self.env['ksg.engineering.weekly.report']
        for project in projects:
            # Cari weekly reports yang jatuh di bulan target
            weekly_reports = WeeklyReport.search([
                ('project_id', '=', project.id),
                ('state', '=', 'done'),
                ('periode_minggu_id.tanggal_mulai', '>=',
                 date(target_year, target_month, 1)),
                ('periode_minggu_id.tanggal_selesai', '<',
                 date(target_year, target_month + 1, 1)
                 if target_month < 12
                 else date(target_year + 1, 1, 1)),
            ])
            if not weekly_reports:
                continue
            existing = self.search([
                ('project_id', '=', project.id),
                ('bulan', '=', target_month),
                ('tahun', '=', target_year),
            ], limit=1)
            planned = sum(weekly_reports.mapped('planned_progress'))
            if not existing:
                existing = self.create({
                    'project_id': project.id,
                    'bulan': target_month,
                    'tahun': target_year,
                    'planned_progress': planned,
                    'state': 'done',
                })
            else:
                existing.planned_progress = planned
            existing.weekly_report_ids = [(6, 0, weekly_reports.ids)]
