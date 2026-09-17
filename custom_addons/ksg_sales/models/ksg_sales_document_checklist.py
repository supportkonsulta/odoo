from odoo import fields, models


class KsgSalesDocumentChecklist(models.Model):
    _name = "ksg.sales.document.checklist"
    _description = "KSG Sales Document Checklist"
    _order = "name"

    name = fields.Char(
        string="Nama Dokumen",
        required=True,
        index=True,
    )

    active = fields.Boolean(
        string="Aktif",
        default=True,
    )