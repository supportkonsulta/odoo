project = env['ksg.sales.project'].search([], limit=1)
if project:
    res = env['ksg.sales.project'].get_kurva_s_data(project.id)
    print("DATA:", res)
else:
    print('No projects')
