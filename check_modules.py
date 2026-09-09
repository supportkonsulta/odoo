import psycopg2

conn = psycopg2.connect(
    dbname='sifnext_dev',
    user='odoo',
    host='127.0.0.1',
    port=5432,
    password='zxcasdqwe12345'
)
cursor = conn.cursor()
cursor.execute(
    "SELECT name, state FROM ir_module_module WHERE name IN %s ORDER BY name",
    (('sifnext_ppl', 'hr_payroll_custom', 'sif_rka', 'sif_keuangan'),)
)
rows = cursor.fetchall()
for row in rows:
    print(row)
conn.close()
