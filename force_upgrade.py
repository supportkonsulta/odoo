modules = env['ir.module.module'].search([('name', 'in', ['ksg_sales', 'ksg_engineering'])])
if modules:
    print(f"Modul ditemukan: {[m.name for m in modules]}")
    modules.button_upgrade()
    env.cr.commit()
    print("Berhasil menandai modul ke status 'To Upgrade' di database!")
else:
    print("Modul tidak ditemukan.")
