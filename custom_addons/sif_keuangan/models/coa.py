from odoo import models, fields, api

class SifChartOfAccounts(models.Model):
    _name = 'sif.coa'
    _description = 'Master Chart of Accounts (COA)'
    _order = 'code asc'
    _rec_name = 'display_name'

    code = fields.Char(string='Kode Akun', required=True, index=True)
    name = fields.Char(string='Nama Akun', required=True)
    account_type = fields.Selection([
        ('asset', 'Aset / Aktiva'),
        ('liability', 'Liabilitas / Kewajiban'),
        ('equity', 'Ekuitas / Modal'),
        ('income', 'Pendapatan'),
        ('expense', 'Beban / Biaya'),
    ], string='Kategori Akun', required=True, default='expense')
    display_name = fields.Char(string='Tampilan Akun', compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Kode Akun sudah terdaftar! Gunakan kode unik.'),
    ]

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"