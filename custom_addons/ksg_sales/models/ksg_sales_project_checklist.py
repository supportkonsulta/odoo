from odoo import fields, models


class KsgSalesProjectChecklist(models.Model):
    _name = "ksg.sales.project.checklist"
    _description = "KSG Sales Project Checklist"
    _order = "id"

    project_id = fields.Many2one(
        comodel_name="ksg.sales.project",
        string="Proyek",
        required=True,
        ondelete="cascade",
    )

    checklist_id = fields.Many2one(
        comodel_name="ksg.sales.document.checklist",
        string="Dokumen",
        required=True,
        ondelete="restrict",
    )

    state = fields.Selection(
        selection=[
            ("not_available", "Belum Ada"),
            ("available", "Ada"),
            ("review", "Review"),
            ("not_applicable", "Tidak Berlaku"),
        ],
        string="Status",
        required=True,
        default="not_available",
    )

    note = fields.Char(
        string="Keterangan",
    )