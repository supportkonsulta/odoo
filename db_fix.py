import psycopg2

conn = psycopg2.connect(host='db', user='odoo', password='odoo', dbname='db_ksg')
cur = conn.cursor()
cur.execute("UPDATE ir_module_module SET installable = true, state = 'installed' WHERE name = 'ksg_operational';")
conn.commit()
print(">>> Berhasil: ksg_operational diset installable=True dan state=installed <<<")
conn.close()