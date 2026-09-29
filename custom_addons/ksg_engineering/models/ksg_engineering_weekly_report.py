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
            
            # Hitung Actual Progress secara absolut (Progress Fisik * Bobot WBS)
            total_progress_by_cost = 0.0
            for cons in approved_cons:
                for dr in cons.daily_report_ids:
                    for line in dr.line_ids:
                        wbs_bobot = line.wbs_id.bobot or 0.0
                        # Progress by cost = (Progress Phisik / 100) * Bobot WBS
                        cost_progress = (line.progress / 100.0) * wbs_bobot
                        total_progress_by_cost += cost_progress
                        
            rec.actual_progress = total_progress_by_cost
            
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
    # EXPORT WEEKLY REPORT (EXCEL)
    # ==================================================================
    def action_export_weekly_report(self):
        self.ensure_one()
        import io
        import base64
        try:
            import xlsxwriter
        except ImportError:
            raise ValidationError("Library xlsxwriter tidak ditemukan di server.")

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('LAPORAN PROGRESS MINGGUAN')
        
        # Formats
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        header_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'text_wrap': True})
        cell_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        center_format = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
        percent_format = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'num_format': '0.00%'})
        
        # Title
        sheet.merge_range('A7:N7', 'LAPORAN PROGRESS MINGGUAN', title_format)
        
        # Meta
        sheet.write('A8', 'PEKERJAAN', workbook.add_format({'bold': True}))
        sheet.write('C8', ':', workbook.add_format({'bold': True}))
        sheet.write('D8', self.project_id.nama_pekerjaan.upper() if self.project_id.nama_pekerjaan else '')
        sheet.write('H8', 'MINGGU KE:', workbook.add_format({'bold': True}))
        sheet.write('I8', self.periode_minggu_id.no_minggu if self.periode_minggu_id else '')
        
        sheet.write('A9', 'KONSULTAN', workbook.add_format({'bold': True}))
        sheet.write('C9', ':', workbook.add_format({'bold': True}))
        sheet.write('D9', self.project_id.klien.name if self.project_id.klien else '')
        sheet.write('H9', 'PERIODE:', workbook.add_format({'bold': True}))
        
        if self.periode_minggu_id:
            period_str = f"{self.periode_minggu_id.tanggal_mulai.strftime('%d %B %Y')} - {self.periode_minggu_id.tanggal_selesai.strftime('%d %B %Y')}"
            sheet.merge_range('I9:K9', period_str)
            
        sheet.write('A10', 'NOMOR SPK', workbook.add_format({'bold': True}))
        sheet.write('C10', ':', workbook.add_format({'bold': True}))
        sheet.write('D10', self.project_id.no_pk or '')
        
        # Headers
        sheet.merge_range('A11:A13', 'No.', header_format)
        sheet.merge_range('B11:B13', 'URAIAN PEKERJAAN', header_format)
        sheet.merge_range('C11:C13', 'UNIT', header_format)
        sheet.merge_range('D11:D13', 'QTY.', header_format)
        sheet.merge_range('E11:E13', 'BOBOT (%)', header_format)
        
        sheet.merge_range('F11:H11', 'PROGRESS BY COST', header_format)
        sheet.merge_range('F12:H12', 'UP TO THIS WEEK', header_format)
        sheet.write('F13', 'MINGGU LALU', header_format)
        sheet.write('G13', 'MINGGU INI', header_format)
        sheet.write('H13', 'SAMPAI MINGGU INI', header_format)
        
        sheet.merge_range('I11:K11', 'PROGRESS BY PHISIK', header_format)
        sheet.merge_range('I12:K12', 'UP TO THIS WEEK', header_format)
        sheet.write('I13', 'MINGGU LALU (%)', header_format)
        sheet.write('J13', 'MINGGU INI (%)', header_format)
        sheet.write('K13', 'SAMPAI MINGGU INI (%)', header_format)
        
        sheet.merge_range('L11:L13', 'KET.', header_format)
        
        sheet.set_column('B:B', 40)
        sheet.set_column('F:K', 15)
        
        # Data
        row = 13
        
        def get_progress_data(w):
            # Jika punya anak, progress = rata-rata tertimbang anak
            if w.child_ids:
                minggu_lalu = 0.0
                minggu_ini = 0.0
                total_bobot_anak = sum(w.child_ids.mapped('bobot')) or 1.0
                
                for c in w.child_ids:
                    c_lalu, c_ini = get_progress_data(c)
                    minggu_lalu += c_lalu * c.bobot
                    minggu_ini += c_ini * c.bobot
                    
                return (minggu_lalu / total_bobot_anak), (minggu_ini / total_bobot_anak)
            else:
                lalu = 0.0
                ini = 0.0
                dr_lines = self.env['ksg.engineering.daily.report.line'].search([
                    ('wbs_id', '=', w.id),
                    ('report_id.state', '=', 'submitted')
                ])
                for line in dr_lines:
                    if line.report_id.tanggal < self.periode_minggu_id.tanggal_mulai:
                        lalu += line.progress
                    elif self.periode_minggu_id.tanggal_mulai <= line.report_id.tanggal <= self.periode_minggu_id.tanggal_selesai:
                        ini += line.progress
                return lalu, ini

        def write_wbs(wbs_list, level, current_row, parent_idx_str=""):
            idx = 1
            for w in wbs_list:
                if level == 1:
                    no_str = f"{idx}"
                else:
                    no_str = f"{parent_idx_str}.{idx}"
                
                prefix = "  " * (level - 1)
                
                minggu_lalu, minggu_ini = get_progress_data(w)
                
                sampai_minggu_ini = min(minggu_lalu + minggu_ini, 100.0)
                minggu_lalu = min(minggu_lalu, 100.0)
                
                cost_lalu = (minggu_lalu / 100.0) * w.bobot
                cost_ini = (minggu_ini / 100.0) * w.bobot
                cost_sampai = (sampai_minggu_ini / 100.0) * w.bobot
                
                sheet.write(current_row, 0, no_str, center_format)
                sheet.write(current_row, 1, prefix + w.nama_pekerjaan, cell_format)
                sheet.write(current_row, 2, w.satuan or '', center_format)
                sheet.write(current_row, 3, w.volume or '', center_format)
                sheet.write(current_row, 4, w.bobot / 100.0, percent_format)
                
                sheet.write(current_row, 5, cost_lalu / 100.0, percent_format)
                sheet.write(current_row, 6, cost_ini / 100.0, percent_format)
                sheet.write(current_row, 7, cost_sampai / 100.0, percent_format)
                
                sheet.write(current_row, 8, minggu_lalu / 100.0, percent_format)
                sheet.write(current_row, 9, minggu_ini / 100.0, percent_format)
                sheet.write(current_row, 10, sampai_minggu_ini / 100.0, percent_format)
                sheet.write(current_row, 11, '', cell_format)
                
                current_row += 1
                
                children = w.child_ids.sorted('id')
                if children:
                    current_row = write_wbs(children, level + 1, current_row, no_str)
                    
                idx += 1
            return current_row
            
        top_wbs = self.env['ksg.engineering.wbs'].search([('project_id', '=', self.project_id.id), ('parent_id', '=', False)]).sorted('id')
        row = write_wbs(top_wbs, 1, row)
        
        workbook.close()
        output.seek(0)
        
        attachment = self.env['ir.attachment'].create({
            'name': f"Weekly_Report_{self.project_id.kode_proyek}_W{self.periode_minggu_id.no_minggu}.xlsx",
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
                    # Hitung planned progress dari WBS target
                    wbs_in_week = self.env['ksg.engineering.wbs'].search([
                        ('project_id', '=', project.id)
                    ])
                    planned = 0.0
                    for wbs in wbs_in_week:
                        target = wbs.target_ids.filtered(lambda t: t.periode_minggu_id.id == week.id)
                        if target:
                            planned += sum(target.mapped('target_progress'))
                            
                    existing = self.create({
                        'project_id': project.id,
                        'periode_minggu_id': week.id,
                        'planned_progress': planned,
                        'state': 'done',
                    })
                existing.consolidation_ids = [(6, 0, cons.ids)]
