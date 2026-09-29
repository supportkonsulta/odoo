wr = env['ksg.engineering.weekly.report'].search([], limit=1)
if wr:
    res = wr.action_export_weekly_report()
    attachment = env['ir.attachment'].browse(int(res['url'].split('/')[-1].split('?')[0]))
    with open('test_weekly.xlsx', 'wb') as f:
        import base64
        f.write(base64.b64decode(attachment.datas))
    print("Saved test_weekly.xlsx")
