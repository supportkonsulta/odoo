"""Daily Report Engineering (FR-006, FR-006A, FR-007).

Pelaksana mengisi daily report per hari per project.
Submit memvalidasi working permit & safety induction (RULE-02).
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date, timedelta


class KsgEngineeringDailyReport(models.Model):
    _name = 'ksg.engineering.daily.report'
    _description = 'Daily Report Engineering'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tanggal desc, id desc'

    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='cascade', index=True, tracking=True)
    tanggal = fields.Date(
        string='Tanggal', required=True, default=fields.Date.context_today,
        tracking=True)
    pelaksana_id = fields.Many2one(
        'res.users', string='Pelaksana', required=True,
        default=lambda self: self.env.user, tracking=True)
    line_ids = fields.One2many(
        'ksg.engineering.daily.report.line', 'report_id',
        string='Detail Pekerjaan')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
    ], string='Status', default='draft', tracking=True, required=True)

    def _compute_display_name(self):
        for rec in self:
            project_name = rec.project_id.kode_proyek or rec.project_id.nama_pekerjaan or ''
            rec.display_name = f"DR-{project_name}-{rec.tanggal}"

    # ==================================================================
    # ACTIONS
    # ==================================================================

    def action_submit(self):
        """Submit daily report. RULE-02: wajib permit lengkap."""
        for rec in self:
            if not rec.project_id.working_permit_ok:
                raise ValidationError(
                    'Tidak dapat submit Daily Report: Working Permit belum lengkap. '
                    'Pastikan dokumen Working Permit sudah ada di checklist project.')
            if not rec.project_id.safety_induction_ok:
                raise ValidationError(
                    'Tidak dapat submit Daily Report: Safety Induction belum lengkap. '
                    'Pastikan dokumen Safety Induction sudah ada di checklist project.')
            if not rec.line_ids:
                raise ValidationError(
                    'Daily Report harus memiliki minimal satu detail pekerjaan.')
            rec.state = 'submitted'

    def action_reset_draft(self):
        """Reset ke draft."""
        for rec in self:
            rec.state = 'draft'

    # ==================================================================
    # CRON: Keterlambatan H+1 (FR-006A)
    # ==================================================================

    @api.model
    def _cron_check_late_report(self):
        """Cek daily report yang belum disubmit H+1."""
        sla_days = int(self.env['ir.config_parameter'].sudo().get_param(
            'ksg_engineering.late_report_sla_days', '1'))
        threshold_date = date.today() - timedelta(days=sla_days)
        late_reports = self.search([
            ('state', '=', 'draft'),
            ('tanggal', '<=', threshold_date),
        ])
        activity_type = self.env.ref(
            'ksg_engineering.activity_late_report', raise_if_not_found=False)
        for report in late_reports:
            existing = self.env['mail.activity'].search([
                ('res_model', '=', self._name),
                ('res_id', '=', report.id),
                ('activity_type_id', '=',
                 activity_type.id if activity_type else False),
            ], limit=1)
            if not existing:
                report.activity_schedule(
                    act_type_xmlid='ksg_engineering.activity_late_report',
                    user_id=report.pelaksana_id.id,
                    summary='Keterlambatan Daily Report',
                    note=f'Daily Report tanggal {report.tanggal} belum disubmit. '
                         f'Sudah melewati SLA {sla_days} hari.')
