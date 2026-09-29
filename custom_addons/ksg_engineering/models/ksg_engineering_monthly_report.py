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
            # Karena laporan mingguan sudah menyimpan nilai absolute (Progress By Cost),
            # kita cukup menjumlahkannya saja.
            rec.actual_progress = sum(
                rec.weekly_report_ids.mapped('actual_progress'))

    @api.depends('planned_progress', 'actual_progress')
    def _compute_variance(self):
        for rec in self:
            rec.variance = rec.actual_progress - rec.planned_progress

    # ==================================================================
    # EXPORT MONTHLY REPORT (EXCEL)
    # ==================================================================
    def action_export_monthly_report(self):
        self.ensure_one()
        import io
        import base64
        from datetime import date
        try:
            import xlsxwriter
        except ImportError:
            raise ValidationError("Library xlsxwriter tidak ditemukan di server.")

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('LAPORAN PROGRESS BULANAN')
        
        # Formats
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        header_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'text_wrap': True})
        cell_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        center_format = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
        percent_format = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'num_format': '0.00%'})
        
        # Title
        sheet.merge_range('A7:N7', 'LAPORAN PROGRESS BULANAN', title_format)
        
        # Meta
        sheet.write('A8', 'PEKERJAAN', workbook.add_format({'bold': True}))
        sheet.write('C8', ':', workbook.add_format({'bold': True}))
        sheet.write('D8', self.project_id.nama_pekerjaan.upper() if self.project_id.nama_pekerjaan else '')
        sheet.write('H8', 'BULAN:', workbook.add_format({'bold': True}))
        sheet.write('I8', f"{self.bulan} / {self.tahun}")
        
        sheet.write('A9', 'KONSULTAN', workbook.add_format({'bold': True}))
        sheet.write('C9', ':', workbook.add_format({'bold': True}))
        sheet.write('D9', self.project_id.klien.name if self.project_id.klien else '')
        
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
        sheet.merge_range('F12:H12', 'UP TO THIS MONTH', header_format)
        sheet.write('F13', 'BULAN LALU', header_format)
        sheet.write('G13', 'BULAN INI', header_format)
        sheet.write('H13', 'SAMPAI BULAN INI', header_format)
        
        sheet.merge_range('I11:K11', 'PROGRESS BY PHISIK', header_format)
        sheet.merge_range('I12:K12', 'UP TO THIS MONTH', header_format)
        sheet.write('I13', 'BULAN LALU (%)', header_format)
        sheet.write('J13', 'BULAN INI (%)', header_format)
        sheet.write('K13', 'SAMPAI BULAN INI (%)', header_format)
        
        sheet.merge_range('L11:L13', 'KET.', header_format)
        
        sheet.set_column('B:B', 40)
        sheet.set_column('F:K', 15)
        
        # Logic helper to get actual physical progress
        # Target month is `self.tahun` and `self.bulan`.
        def get_progress_data(w):
            if w.child_ids:
                lalu = 0.0
                ini = 0.0
                total_bobot_anak = sum(w.child_ids.mapped('bobot')) or 1.0
                for c in w.child_ids:
                    c_lalu, c_ini = get_progress_data(c)
                    lalu += c_lalu * c.bobot
                    ini += c_ini * c.bobot
                return (lalu / total_bobot_anak), (ini / total_bobot_anak)
            else:
                lalu = 0.0
                ini = 0.0
                dr_lines = self.env['ksg.engineering.daily.report.line'].search([
                    ('wbs_id', '=', w.id),
                    ('report_id.state', '=', 'submitted')
                ])
                for line in dr_lines:
                    rt = line.report_id.tanggal
                    if rt.year < self.tahun or (rt.year == self.tahun and rt.month < self.bulan):
                        lalu += line.progress
                    elif rt.year == self.tahun and rt.month == self.bulan:
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
                
                bln_lalu, bln_ini = get_progress_data(w)
                
                sampai_bln_ini = min(bln_lalu + bln_ini, 100.0)
                bln_lalu = min(bln_lalu, 100.0)
                
                cost_lalu = (bln_lalu / 100.0) * w.bobot
                cost_ini = (bln_ini / 100.0) * w.bobot
                cost_sampai = (sampai_bln_ini / 100.0) * w.bobot
                
                sheet.write(current_row, 0, no_str, center_format)
                sheet.write(current_row, 1, prefix + w.nama_pekerjaan, cell_format)
                sheet.write(current_row, 2, w.satuan or '', center_format)
                sheet.write(current_row, 3, w.volume or '', center_format)
                sheet.write(current_row, 4, w.bobot / 100.0, percent_format)
                
                sheet.write(current_row, 5, cost_lalu / 100.0, percent_format)
                sheet.write(current_row, 6, cost_ini / 100.0, percent_format)
                sheet.write(current_row, 7, cost_sampai / 100.0, percent_format)
                
                sheet.write(current_row, 8, bln_lalu / 100.0, percent_format)
                sheet.write(current_row, 9, bln_ini / 100.0, percent_format)
                sheet.write(current_row, 10, sampai_bln_ini / 100.0, percent_format)
                sheet.write(current_row, 11, '', cell_format)
                
                current_row += 1
                
                children = w.child_ids.sorted('id')
                if children:
                    current_row = write_wbs(children, level + 1, current_row, no_str)
                    
                idx += 1
            return current_row
            
        top_wbs = self.env['ksg.engineering.wbs'].search([('project_id', '=', self.project_id.id), ('parent_id', '=', False)]).sorted('id')
        row = 13
        write_wbs(top_wbs, 1, row)
        
        workbook.close()
        output.seek(0)
        
        attachment = self.env['ir.attachment'].create({
            'name': f"Monthly_Report_{self.project_id.kode_proyek}_{self.tahun}_{self.bulan:02d}.xlsx",
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
