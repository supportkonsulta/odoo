import odoo
from odoo import api, SUPERUSER_ID

odoo.tools.config.parse_config(['-d', 'db_ksg', '--db_host=db', '-r', 'odoo', '-w', 'odoo'])
registry = odoo.registry('db_ksg')
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    modules = env['ir.module.module'].search([('name', 'in', ['ksg_sales', 'ksg_operational'])])
    for m in modules:
        print(f"Modul {m.name} -> Status: {m.state}")
    
    # Paksa status ke 'installed' agar siap di-upgrade via flag -u
    cr.execute("UPDATE ir_module_module SET state = 'installed' WHERE name IN ('ksg_sales', 'ksg_operational');")
    cr.commit()
    print("Status database berhasil diselaraskan ke 'installed'.")