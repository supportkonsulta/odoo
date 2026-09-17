from odoo import fields, models


class KsgSalesCategory(models.Model):
    _name = "ksg.sales.category"
    _description = "KSG Sales Category"
    _order = "name"

    name = fields.Char(
        string="Nama Kategori",
        required=True,
        index=True,
    )

    active = fields.Boolean(
        string="Aktif",
        default=True,
    )

    default_checklist_ids = fields.Many2many(
        comodel_name="ksg.sales.document.checklist",
        relation="ksg_sales_category_checklist_rel",
        column1="category_id",
        column2="checklist_id",
        string="Default Checklist Dokumen",
    )