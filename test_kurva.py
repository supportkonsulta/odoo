project = env['ksg.sales.project'].search([], limit=1)
if project:
    print('Project ID:', project.id)
    try:
        res = env['ksg.sales.project'].get_kurva_s_data(project.id)
        print('Result:', res)
    except Exception as e:
        print('Error:', e)
else:
    print('No projects found')
