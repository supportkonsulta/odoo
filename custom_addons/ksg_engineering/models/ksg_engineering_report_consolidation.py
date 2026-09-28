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
        """Supervisor menyetujui konsolidasi dan otomatis update Laporan Mingguan."""
        for rec in self:
            if rec.state != 'waiting_approval':
                raise ValidationError(
                    'Hanya konsolidasi dengan status "Menunggu Approval" '
                    'yang bisa disetujui.')
            rec.state = 'approved'
            rec.catatan_revisi = False
            
            # 1. Hapus (unlink) notifikasi pending approval agar tidak error
            rec.activity_unlink(['ksg_engineering.activity_pending_approval'])
                
            # 2. OTOMATIS UPDATE LAPORAN MINGGUAN (Agar Kurva-S langsung bergerak)
            if rec.periode_minggu_id:
                WeeklyReport = self.env['ksg.engineering.weekly.report']
                existing_weekly = WeeklyReport.search([
                    ('project_id', '=', rec.project_id.id),
                    ('periode_minggu_id', '=', rec.periode_minggu_id.id)
                ], limit=1)
                
                if not existing_weekly:
                    # Hitung planned progress dari WBS target untuk minggu ini
                    wbs_in_week = self.env['ksg.engineering.wbs'].search([
                        ('project_id', '=', rec.project_id.id)
                    ])
                    planned = 0.0
                    for wbs in wbs_in_week:
                        target = wbs.target_ids.filtered(lambda t: t.periode_minggu_id.id == rec.periode_minggu_id.id)
                        if target:
                            planned += sum(target.mapped('target_progress'))
                            
                    existing_weekly = WeeklyReport.create({
                        'project_id': rec.project_id.id,
                        'periode_minggu_id': rec.periode_minggu_id.id,
                        'planned_progress': planned,
                        'state': 'done',
                    })
                
                # Tambahkan konsolidasi ini ke weekly report
                existing_weekly.consolidation_ids = [(4, rec.id)]
                # Paksa recompute actual_progress
                existing_weekly._compute_progress()
                existing_weekly.project_id._compute_kurva_s()

    def action_pull_daily_reports(self):
        """Otomatis menarik daily report yang disubmit pada minggu yang dipilih."""
        for rec in self:
            if not rec.periode_minggu_id:
                raise ValidationError("Pilih Periode Minggu terlebih dahulu.")
                
            daily_reports = self.env['ksg.engineering.daily.report'].search([
                ('project_id', '=', rec.project_id.id),
                ('state', '=', 'submitted'),
                ('tanggal', '>=', rec.periode_minggu_id.tanggal_mulai),
                ('tanggal', '<=', rec.periode_minggu_id.tanggal_selesai)
            ])
            
            if not daily_reports:
                raise ValidationError(
                    f"Tidak ada Laporan Harian dengan status 'Submitted' "
                    f"untuk periode {rec.periode_minggu_id.tanggal_mulai} s/d {rec.periode_minggu_id.tanggal_selesai}."
                )
                
            rec.daily_report_ids = [(6, 0, daily_reports.ids)]

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
            
            # Hapus (unlink) notifikasi pending approval
            rec.activity_unlink(['ksg_engineering.activity_pending_approval'])
                
            # Notify pengawas
            rec.activity_schedule(
                act_type_xmlid='ksg_engineering.activity_pending_approval',
                user_id=rec.pengawas_id.id,
                summary='Konsolidasi Perlu Revisi',
                note=f'Konsolidasi dikembalikan untuk revisi. Catatan: {rec.catatan_revisi}')

    def action_reset_draft(self):
        """Reset ke draft (dari revisi)."""
        for rec in self:
            rec.state = 'draft'
