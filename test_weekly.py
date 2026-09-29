wr = env['ksg.engineering.weekly.report'].search([], limit=1)
if wr:
    print("Found WR:", wr.display_name)
    wbs_list = env['ksg.engineering.wbs'].search([('project_id', '=', wr.project_id.id), ('parent_id', '=', False)])
    for w in wbs_list:
        dr_lines = env['ksg.engineering.daily.report.line'].search([
            ('wbs_id', '=', w.id),
            ('report_id.state', '=', 'submitted')
        ])
        print(f"WBS: {w.nama_pekerjaan} - Daily lines: {len(dr_lines)}")
        for l in dr_lines:
            print(f"  - {l.report_id.tanggal}: {l.progress}%")
        if w.child_ids:
            print("  Has children:", len(w.child_ids))
            for c in w.child_ids:
                c_lines = env['ksg.engineering.daily.report.line'].search([
                    ('wbs_id', '=', c.id),
                    ('report_id.state', '=', 'submitted')
                ])
                print(f"  - Child {c.nama_pekerjaan} - Daily lines: {len(c_lines)}")
else:
    print("No WR found")
