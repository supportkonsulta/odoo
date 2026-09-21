"""Weekly Report Engineering (FR-009, FR-010).

Agregasi dari konsolidasi approved per minggu.
Generated via ir.cron (RULE-06).
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class KsgEngineeringWeeklyReport(models.Model):
    _name = 'ksg.engineering.weekly.report'
    _description = 'Laporan Mingguan Engineering'
    _inherit = ['mail.thread']
    _order = 'project_id, periode_minggu_id'

    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='cascade', index=True, tracking=True)
    periode_minggu_id = fields.Many2one(
        'ksg.engineering.schedule.week', string='Periode Minggu',
        required=True, domain="[('project_id', '=', project_id)]",
        tracking=True)
    consolidation_ids = fields.Many2many(
        'ksg.engineering.report.consolidation',
        relation='ksg_eng_weekly_cons_rel',
        string='Konsolidasi Terkait')

    planned_progress = fields.Float(
        string='Planned Progress (%)', digits=(5, 2))
    actual_progress = fields.Float(
        string='Actual Progress (%)', digits=(5, 2),
        compute='_compute_progress', store=True)
    actual_progress_kumulatif = fields.Float(
        string='Actual Kumulatif (%)', digits=(5, 2),
        compute='_compute_progress', store=True)
    variance = fields.Float(
        string='Variance (%)', compute='_compute_variance',
        store=True, digits=(5, 2))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Selesai'),
    ], string='Status', default='draft', tracking=True, required=True)

    def _compute_display_name(self):
        for rec in self:
            project_name = rec.project_id.kode_proyek or ''
            week = rec.periode_minggu_id.no_minggu if rec.periode_minggu_id else 0
            rec.display_name = f"WR-{project_name}-W{week}"

    @api.depends('consolidation_ids.state', 'consolidation_ids.daily_report_ids.line_ids.progress')
    def _compute_progress(self):
        for rec in self:
            approved_cons = rec.consolidation_ids.filtered(
                lambda c: c.state == 'approved')
            total_progress = 0.0
            for cons in approved_cons:
                for dr in cons.daily_report_ids:
                    for line in dr.line_ids:
                        total_progress += line.progress
            rec.actual_progress = total_progress
            # Kumulatif: sum all weekly reports up to this week
            prev_weeks = self.search([
                ('project_id', '=', rec.project_id.id),
                ('state', '=', 'done'),
                ('periode_minggu_id.no_minggu', '<',
                 rec.periode_minggu_id.no_minggu if rec.periode_minggu_id else 0),
            ])
            rec.actual_progress_kumulatif = (
                sum(prev_weeks.mapped('actual_progress')) + rec.actual_progress)

    @api.depends('planned_progress', 'actual_progress')
    def _compute_variance(self):
        for rec in self:
            rec.variance = rec.actual_progress - rec.planned_progress

    # ==================================================================
    # CRON: Generate weekly (RULE-06)
    # ==================================================================

    @api.model
    def _cron_generate_weekly(self):
        """Cron mingguan: buat/update weekly report dari konsolidasi approved."""
        projects = self.env['ksg.sales.project'].search([
            ('status', '=', 'aktif'),
        ])
        Consolidation = self.env['ksg.engineering.report.consolidation']
        for project in projects:
            for week in project.schedule_week_ids:
                # Cari konsolidasi approved di minggu ini
                cons = Consolidation.search([
                    ('project_id', '=', project.id),
                    ('periode_minggu_id', '=', week.id),
                    ('state', '=', 'approved'),
                ])
                if not cons:
                    continue
                existing = self.search([
                    ('project_id', '=', project.id),
                    ('periode_minggu_id', '=', week.id),
                ], limit=1)
                if not existing:
                    # Hitung planned progress dari WBS
                    wbs_in_week = self.env['ksg.engineering.wbs'].search([
                        ('project_id', '=', project.id),
                        ('periode_minggu_ids', 'in', [week.id]),
                    ])
                    planned = sum(wbs_in_week.mapped('planned_progress_mingguan'))
                    existing = self.create({
                        'project_id': project.id,
                        'periode_minggu_id': week.id,
                        'planned_progress': planned,
                        'state': 'done',
                    })
                existing.consolidation_ids = [(6, 0, cons.ids)]
