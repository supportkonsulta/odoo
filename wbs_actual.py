        def get_actual_progress(w):
            lalu = 0.0
            ini = 0.0
            dr_lines = self.env['ksg.engineering.daily.report.line'].search([
                ('wbs_id', '=', w.id),
                ('report_id.state', '=', 'submitted')
            ])
            for line in dr_lines:
                # We want it grouped by week, so we need a way to distribute line.progress into weeks
                pass

