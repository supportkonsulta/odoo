users_data = [
    {'name': 'Human Capital Staff', 'login': 'hc', 'password': 'hc123', 'email': 'hc@ksg.co.id'},
    {'name': 'Staff Operasional', 'login': 'operasional', 'password': 'operasional123', 'email': 'ops@ksg.co.id'},
    {'name': 'Manajer Keuangan', 'login': 'keuangan', 'password': 'keuangan123', 'email': 'keuangan@ksg.co.id'},
    {'name': 'Direktur Utama', 'login': 'direktur', 'password': 'direktur123', 'email': 'direktur@ksg.co.id'}
]

for u in users_data:
    existing = env['res.users'].search([('login', '=', u['login'])])
    if existing:
        existing.write({'password': u['password'], 'name': u['name']})
        print(f"User {u['login']} updated.")
    else:
        env['res.users'].create({
            'name': u['name'],
            'login': u['login'],
            'password': u['password'],
            'email': u['email'],
            'groups_id': [(6, 0, [env.ref('base.group_user').id])]
        })
        print(f"User {u['login']} created.")
env.cr.commit()