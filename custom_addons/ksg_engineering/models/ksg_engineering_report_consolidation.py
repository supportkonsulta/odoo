"""Report Consolidation — Pengawas konsolidasi daily report (FR-008, FR-008A).

Workflow: draft → waiting_approval → approved / revisi
Approval oleh Supervisor. Revisi wajib catatan (RULE-05).
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class KsgEngineeringReportConsolidation(models.Model):
    _name = 'ksg.engineering.report.consolidation'
    _description = 'Konsolidasi Laporan Engineering'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='cascade', index=True, tracking=True)
    daily_report_ids = fields.Many2many(
        'ksg.engineering.daily.report', 
        relation='ksg_eng_cons_daily_rel',
        string='Daily Report',
        domain="[('project_id', '=', project_id), ('state', '=', 'submitted')]")
    pengawas_id = fields.Many2one(
        'res.users', string='Pengawas', required=True,
        default=lambda self: self.env.user, tracking=True)
    periode_minggu_id = fields.Many2one(
        'ksg.engineering.schedule.week', string='Periode Minggu',
        domain="[('project_id', '=', project_id)]", tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_approval', 'Menunggu Approval'),
        ('approved', 'Approved'),
        ('revisi', 'Revisi'),
    ], string='Status', default='draft', tracking=True, required=True)
    catatan_revisi = fields.Text(string='Catatan Revisi', tracking=True)

    def _compute_display_name(self):
        for rec in self:
            project_name = rec.project_id.kode_proyek or ''
            week_name = f"W{rec.periode_minggu_id.no_minggu}" if rec.periode_minggu_id else ''
            rec.display_name = f"CONS-{project_name}-{week_name}"

    # ==================================================================
    # ACTIONS (RULE-05: approval berjenjang)
    # ==================================================================

    def action_ajukan(self):
        """Pengawas mengajukan konsolidasi ke Supervisor."""
        for rec in self:
            if not rec.daily_report_ids:
                raise ValidationError(
                    'Konsolidasi harus memiliki minimal satu Daily Report.')
            rec.state = 'waiting_approval'
            # Schedule activity ke Supervisor yang ter-assign di project
            supervisors = rec.project_id.assignment_ids.filtered(
                lambda a: a.active and a.peran in (
                    'supervisor', 'kepala_unit')
            ).mapped('user_id')
            for user in supervisors:
                rec.activity_schedule(
                    act_type_xmlid='ksg_engineering.activity_pending_approval',
                    user_id=user.id,
                    summary='Konsolidasi Menunggu Approval',
                    note=f'Konsolidasi dari {rec.pengawas_id.name} '
                         f'menunggu persetujuan Anda.')

    def action_approve(self):
        """Supervisor menyetujui konsolidasi."""
        for rec in self:
            if rec.state != 'waiting_approval':
                raise ValidationError(
                    'Hanya konsolidasi dengan status "Menunggu Approval" '
                    'yang bisa disetujui.')
            rec.state = 'approved'
            rec.catatan_revisi = False
            # Mark activities as done
            rec.activity_feedback(
                act_type_xmlid='ksg_engineering.activity_pending_approval',
                feedback='Konsolidasi disetujui.')

    def action_revisi(self):
        """Supervisor meminta revisi. RULE-05: wajib catatan_revisi."""
        for rec in self:
            if rec.state != 'waiting_approval':
                raise ValidationError(
                    'Hanya konsolidasi dengan status "Menunggu Approval" '
                    'yang bisa direvisi.')
            if not rec.catatan_revisi:
                raise ValidationError(
                    'Catatan revisi wajib diisi sebelum meminta revisi.')
            rec.state = 'revisi'
            # Notify pengawas
            rec.activity_schedule(
                act_type_xmlid='ksg_engineering.activity_pending_approval',
                user_id=rec.pengawas_id.id,
                summary='Konsolidasi Perlu Revisi',
                note=f'Konsolidasi dikembalikan untuk revisi. '
                     f'Catatan: {rec.catatan_revisi}')

    def action_reset_draft(self):
        """Reset ke draft (dari revisi)."""
        for rec in self:
            rec.state = 'draft'
