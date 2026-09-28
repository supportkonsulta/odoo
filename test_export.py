wr = env['ksg.engineering.weekly.report'].search([], limit=1)
if wr:
    try:
        wr.action_export_weekly_report()
        print('SUCCESS')
    except Exception as e:
        import traceback
        traceback.print_exc()
else:
    print('No weekly report')
