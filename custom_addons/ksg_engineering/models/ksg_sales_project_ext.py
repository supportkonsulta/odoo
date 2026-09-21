"""Extend ksg.sales.project dengan field-field Engineering.

Sesuai plan Section 2.2 (Skenario B/C): ksg_sales sudah ada.
Field mapping:
  - name       → kode_proyek (via _rec_name di Sales)
  - partner_id → klien (related)
  - state      → status (mapping via _is_active_state)
  - document_ids → tidak ada di Sales, ditambah di sini (TODO)
  - checklist tipe/status → tidak ada, computed via boolean
"""

from odoo import models, fields, api
from datetime import timedelta


class KsgSalesProjectExt(models.Model):
    _inherit = 'ksg.sales.project'

    # ------------------------------------------------------------------
    # Related fields — mapping nama field Sales → konvensi Engineering
    # Sesuai Section 2.2.1: jangan rename field Sales, buat related.
    # ------------------------------------------------------------------
    partner_id = fields.Many2one(
        related='klien', string='Partner (Engineering ref)',
        store=True, readonly=True)

    # ------------------------------------------------------------------
    # Document prerequisites (FR-002A)
    # ksg.sales.document.checklist di Sales hanya punya name & active,
    # tidak ada tipe & status. Kita sediakan field boolean di sini.
    # TODO: Pindahkan tipe/status ke ksg_sales saat modul Sales diupdate.
    # ------------------------------------------------------------------
    working_permit_ok = fields.Boolean(
        string='Working Permit OK', compute='_compute_document_prerequisites',
        store=True, tracking=True,
        help='True jika Working Permit sudah dilengkapi.')
    safety_induction_ok = fields.Boolean(
        string='Safety Induction OK', compute='_compute_document_prerequisites',
        store=True, tracking=True,
        help='True jika Safety Induction sudah dilengkapi.')

    # ------------------------------------------------------------------
    # Engineering One2many relations
    # ------------------------------------------------------------------
    schedule_week_ids = fields.One2many(
        'ksg.engineering.schedule.week', 'project_id',
        string='Kalender Minggu')
    wbs_ids = fields.One2many(
        'ksg.engineering.wbs', 'project_id', string='WBS')
    assignment_ids = fields.One2many(
        'ksg.engineering.assignment', 'project_id', string='Assignment')
    bapbast_ids = fields.One2many(
        'ksg.engineering.bapbast', 'project_id', string='BAP/BAST')

    # ------------------------------------------------------------------
    # BAP/BAST approved flag — consumed by ksg_billing downstream
    # ------------------------------------------------------------------
    bapbast_approved = fields.Boolean(
        string='BAP/BAST Disetujui', compute='_compute_bapbast_approved',
        store=True, tracking=True)

    # ------------------------------------------------------------------
    # Notification config
    # ------------------------------------------------------------------
    notify_email_enabled = fields.Boolean(
        string='Notifikasi Email Aktif', default=False,
        help='Jika True, notifikasi juga dikirim via email selain in-app activity.')

    # ------------------------------------------------------------------
    # Kurva-S cache (FR-010)
    # ------------------------------------------------------------------
    kurva_s_planned = fields.Float(
        string='Kurva-S Planned (%)', compute='_compute_kurva_s',
        digits=(5, 2))
    kurva_s_actual = fields.Float(
        string='Kurva-S Actual (%)', compute='_compute_kurva_s',
        digits=(5, 2))
    kurva_s_variance = fields.Float(
        string='Kurva-S Variance (%)', compute='_compute_kurva_s',
        digits=(5, 2))

    # ------------------------------------------------------------------
    # Document attachments (TODO: idealnya milik ksg_sales)
    # ------------------------------------------------------------------
    document_ids = fields.Many2many(
        'ir.attachment', 'ksg_eng_project_attachment_rel',
        'project_id', 'attachment_id',
        string='Dokumen Teknis',
        help='TODO: Pindahkan field ini ke ksg_sales saat modul Sales diupdate. '
             'Sementara disediakan di sini agar Engineering bisa berjalan.')

    # ==================================================================
    # COMPUTES
    # ==================================================================

    @api.depends('checklist_dokumen_ids.name')
    def _compute_document_prerequisites(self):
        """Karena ksg.sales.document.checklist tidak punya field tipe & status,
        kita cek berdasarkan nama dokumen (contains 'working permit' /
        'safety induction'). Pendekatan ini bersifat sementara.
        TODO: Sinkronkan dengan ksg_sales jika tipe/status ditambahkan."""
        for rec in self:
            checklist_names = rec.checklist_dokumen_ids.mapped('name')
            lower_names = [n.lower() for n in checklist_names if n]
            rec.working_permit_ok = any(
                'working permit' in n for n in lower_names)
            rec.safety_induction_ok = any(
                'safety induction' in n for n in lower_names)

    @api.depends('bapbast_ids.state')
    def _compute_bapbast_approved(self):
        for rec in self:
            rec.bapbast_approved = any(
                b.state == 'approved' for b in rec.bapbast_ids)

    @api.depends('wbs_ids.planned_progress_kumulatif',
                 'wbs_ids.bobot')
    def _compute_kurva_s(self):
        for rec in self:
            top_wbs = rec.wbs_ids.filtered(lambda w: not w.parent_id)
            total_bobot = sum(top_wbs.mapped('bobot'))
            if total_bobot:
                planned = sum(
                    w.planned_progress_kumulatif * w.bobot
                    for w in top_wbs) / total_bobot
                actual = sum(
                    w.actual_progress_kumulatif * w.bobot
                    for w in top_wbs) / total_bobot
            else:
                planned = 0.0
                actual = 0.0
            rec.kurva_s_planned = planned
            rec.kurva_s_actual = actual
            rec.kurva_s_variance = actual - planned

    # ==================================================================
    # Calendar weeks generation (FR-011)
    # ==================================================================

    def _compute_calendar_weeks(self):
        """Generate schedule.week records berdasarkan periode kontrak."""
        ScheduleWeek = self.env['ksg.engineering.schedule.week']
        for rec in self:
            if not rec.awal_kontrak or not rec.akhir_kontrak:
                continue
            if rec.akhir_kontrak < rec.awal_kontrak:
                continue
            existing = ScheduleWeek.search([('project_id', '=', rec.id)])
            existing.unlink()
            start = rec.awal_kontrak
            week_no = 1
            while start <= rec.akhir_kontrak:
                end = min(start + timedelta(days=6), rec.akhir_kontrak)
                ScheduleWeek.create({
                    'project_id': rec.id,
                    'no_minggu': week_no,
                    'tanggal_mulai': start,
                    'tanggal_selesai': end,
                })
                start = end + timedelta(days=1)
                week_no += 1

    def action_generate_calendar_weeks(self):
        """Button action to generate calendar weeks."""
        self._compute_calendar_weeks()
        return True

    # ==================================================================
    # Abstraction layer (Section 2.4)
    # ==================================================================

    def _is_active_state(self):
        """Mapping state Sales riil ke konsep 'aktif' Engineering.
        ksg_sales menggunakan field 'status' dengan values aktif/selesai/batal."""
        return self.status in ('aktif',)

    def _get_nilai_kontrak(self):
        """Abstraction: baca nilai kontrak dari Sales.
        Ubah di sini jika nama field Sales berubah."""
        return self.nilai_kontrak_terkini

    # ==================================================================
    # Cron: Kurva-S alert (FR-010A)
    # ==================================================================

    @api.model
    def _cron_check_kurva_s_alert(self):
        """Cron mingguan: cek variance Kurva-S < threshold, kirim activity."""
        threshold = float(self.env['ir.config_parameter'].sudo().get_param(
            'ksg_engineering.variance_threshold', '-5.0'))
        projects = self.search([('status', '=', 'aktif')])
        activity_type = self.env.ref(
            'ksg_engineering.activity_kurva_s_alert', raise_if_not_found=False)
        for project in projects:
            if project.kurva_s_variance < threshold:
                # Cari Kepala Unit / Supervisor yang ter-assign
                supervisors = project.assignment_ids.filtered(
                    lambda a: a.active and a.peran in (
                        'kepala_unit', 'supervisor')
                ).mapped('user_id')
                for user in supervisors:
                    existing = self.env['mail.activity'].search([
                        ('res_model', '=', self._name),
                        ('res_id', '=', project.id),
                        ('activity_type_id', '=',
                         activity_type.id if activity_type else False),
                        ('user_id', '=', user.id),
                    ], limit=1)
                    if not existing:
                        project.activity_schedule(
                            act_type_xmlid='ksg_engineering.activity_kurva_s_alert',
                            user_id=user.id,
                            summary='Peringatan Keterlambatan Kurva-S',
                            note=f'Variance Kurva-S: {project.kurva_s_variance:.2f}% '
                                 f'(threshold: {threshold}%)')
