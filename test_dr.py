w = env['ksg.engineering.wbs'].search([], limit=1)
if w:
    dr_lines = env['ksg.engineering.daily.report.line'].search([
        ('wbs_id', '=', w.id),
        ('report_id.state', '=', 'submitted')
    ])
    print('Daily report lines:', len(dr_lines))
    for l in dr_lines:
        print(' -', l.report_id.tanggal, l.progress)
