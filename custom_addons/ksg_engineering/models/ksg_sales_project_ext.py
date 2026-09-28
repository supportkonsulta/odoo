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
        string='Working Permit OK', tracking=True,
        help='Centang jika Working Permit sudah dilengkapi.')
    safety_induction_ok = fields.Boolean(
        string='Safety Induction OK', tracking=True,
        help='Centang jika Safety Induction sudah dilengkapi.')

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
    # KURVA-S DATA PROVIDER FOR WIDGET
    # ==================================================================
    
    @api.model
    def get_kurva_s_data(self, project_id):
        """Mengirimkan data Rencana dan Realisasi per minggu ke Widget Kurva-S."""
        project = self.browse(project_id)
        if not project.exists() or not project.schedule_week_ids:
            return {'hasData': False}
            
        weeks = project.schedule_week_ids.sorted('no_minggu')
        labels = []
        planned = []
        actual = []
        
        cum_planned = 0.0
        cum_actual = 0.0
        
        top_wbs = project.wbs_ids.filtered(lambda w: not w.parent_id)
        total_bobot = sum(top_wbs.mapped('bobot')) or 1.0 # Hindari div by zero
        
        for w in weeks:
            labels.append(f"W{w.no_minggu}")
            
            # Hitung Rencana Kumulatif s/d minggu ini
            # Bobot WBS yang dialokasikan s/d minggu ini dari wbs.target
            week_planned = 0.0
            for wbs in top_wbs:
                target = wbs.target_ids.filtered(lambda t: t.periode_minggu_id.id == w.id)
                if target:
                    week_planned += sum(target.mapped('target_progress'))
            cum_planned += week_planned
            planned.append(round(min(cum_planned, 100.0), 2))
            
            # Hitung Realisasi Kumulatif s/d minggu ini
            # Ambil semua Laporan Harian yang dikonsolidasi s/d minggu ini
            cons = self.env['ksg.engineering.report.consolidation'].search([
                ('project_id', '=', project.id),
                ('periode_minggu_id.tanggal_selesai', '<=', w.tanggal_selesai),
                ('state', '=', 'approved')
            ])
            
            # Total progress = sum(line.progress * bobot)
            # Karena logic ini cukup berat, kita ambil actual_progress_kumulatif dari WBS saat ini saja
            # tapi itu tidak mencerminkan per minggu. 
            # Solusi cepat: gunakan data dari Laporan Mingguan jika ada.
            weekly_rep = self.env['ksg.engineering.weekly.report'].search([
                ('project_id', '=', project.id),
                ('periode_minggu_id', '=', w.id),
                ('state', '=', 'done')
            ], limit=1)
            
            if weekly_rep:
                cum_actual = weekly_rep.actual_progress_kumulatif
            actual.append(round(min(cum_actual, 100.0), 2))
            
        return {
            'hasData': True,
            'labels': labels,
            'planned': planned,
            'actual': actual
        }

    # ==================================================================
    # EXPORT MASTER SCHEDULE (EXCEL)
    # ==================================================================
    def action_export_master_schedule(self):
        self.ensure_one()
        import io
        import base64
        try:
            import xlsxwriter
        except ImportError:
            raise ValidationError("Library xlsxwriter tidak ditemukan di server.")

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('MASTER SCHEDULE')
        
        # Formats
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center', 'valign': 'vcenter'})
        header_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#D3D3D3'})
        cell_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        center_format = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
        percent_format = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'num_format': '0.00%'})
        
        # Title
        sheet.merge_range('A1:J1', 'MASTER SCHEDULE PEKERJAAN', title_format)
        sheet.merge_range('A2:J2', self.nama_pekerjaan.upper() if self.nama_pekerjaan else '', title_format)
        
        # Meta
        sheet.write('A4', 'KONSULTAN / KLIEN:', workbook.add_format({'bold': True}))
        sheet.write('C4', self.klien.name if self.klien else '')
        sheet.write('A5', 'NOMOR KONTRAK / SP:', workbook.add_format({'bold': True}))
        sheet.write('C5', self.no_pk or '')
        sheet.write('A6', 'TANGGAL KONTRAK:', workbook.add_format({'bold': True}))
        sheet.write('C6', f"{self.awal_kontrak.strftime('%d %b %Y')} s.d {self.akhir_kontrak.strftime('%d %b %Y')}" if self.awal_kontrak and self.akhir_kontrak else '')
        
        # Table Headers
        row = 8
        sheet.write(row, 0, 'NO', header_format)
        sheet.write(row, 1, 'URAIAN PEKERJAAN', header_format)
        sheet.write(row, 2, 'BOBOT (%)', header_format)
        
        weeks = self.schedule_week_ids.sorted('no_minggu')
        col = 3
        for w in weeks:
            sheet.write(row, col, f"M-{w.no_minggu}\n{w.tanggal_mulai.strftime('%d/%m')}-{w.tanggal_selesai.strftime('%d/%m')}", header_format)
            sheet.set_column(col, col, 12)
            col += 1
            
        sheet.write(row, col, 'TOTAL (%)', header_format)
        sheet.set_column(0, 0, 5)
        sheet.set_column(1, 1, 40)
        sheet.set_column(2, 2, 10)
        
        # Data Rows
        row += 1
        
        def write_wbs(wbs_list, level, current_row):
            idx = 1
            for w in wbs_list:
                prefix = ""
                if level == 1:
                    # Convert to Roman
                    val = idx
                    roman = ''
                    num = [1, 4, 5, 9, 10, 40, 50, 90, 100, 400, 500, 900, 1000]
                    sym = ["I", "IV", "V", "IX", "X", "XL", "L", "XC", "C", "CD", "D", "CM", "M"]
                    i = 12
                    while val:
                        div = val // num[i]
                        val %= num[i]
                        while div:
                            roman += sym[i]
                            div -= 1
                        i -= 1
                    no_str = roman
                else:
                    no_str = f"{idx}"
                    prefix = "  " * level
                    
                sheet.write(current_row, 0, no_str, center_format)
                sheet.write(current_row, 1, prefix + w.nama_pekerjaan, cell_format)
                sheet.write(current_row, 2, w.bobot / 100.0, percent_format)
                
                # Targets
                c = 3
                for wk in weeks:
                    target = w.target_ids.filtered(lambda t: t.periode_minggu_id.id == wk.id)
                    val = sum(target.mapped('target_progress')) / 100.0 if target else 0.0
                    if val > 0:
                        sheet.write(current_row, c, val, percent_format)
                    else:
                        sheet.write(current_row, c, '', cell_format)
                    c += 1
                    
                sheet.write(current_row, c, sum(w.target_ids.mapped('target_progress')) / 100.0, percent_format)
                current_row += 1
                
                # Children
                children = w.child_ids.sorted('id')
                if children:
                    current_row = write_wbs(children, level + 1, current_row)
                    
                idx += 1
            return current_row
            
        top_wbs = self.wbs_ids.filtered(lambda w: not w.parent_id).sorted('id')
        row = write_wbs(top_wbs, 1, row)
        
        # Footer
        sheet.write(row, 1, 'GRAND TOTAL', workbook.add_format({'bold': True, 'align': 'right', 'border': 1}))
        sheet.write(row, 2, sum(top_wbs.mapped('bobot')) / 100.0, workbook.add_format({'bold': True, 'align': 'center', 'border': 1, 'num_format': '0.00%'}))
        
        c = 3
        for wk in weeks:
            total_wk = 0.0
            for w in top_wbs:
                target = w.target_ids.filtered(lambda t: t.periode_minggu_id.id == wk.id)
                if target:
                    total_wk += sum(target.mapped('target_progress'))
            sheet.write(row, c, total_wk / 100.0, workbook.add_format({'bold': True, 'align': 'center', 'border': 1, 'num_format': '0.00%'}))
            c += 1
            
        sheet.write(row, c, '', cell_format)
        
        workbook.close()
        output.seek(0)
        
        attachment = self.env['ir.attachment'].create({
            'name': f"Master_Schedule_{self.kode_proyek}.xlsx",
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

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
