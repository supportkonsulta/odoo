from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    ksg_term_id = fields.Many2one(
        "ksg.sales.project.term",
        string="Termin Penagihan",
        copy=False,
        readonly=True,
    )

    ksg_project_id = fields.Many2one(
        "ksg.sales.project",
        string="Proyek KSG",
        related="ksg_term_id.project_id",
        store=True,
        readonly=True,
    )

    def action_print_ksg_invoice(self):
        self.ensure_one()

        return self.env.ref(
            "ksg_sales.action_report_ksg_invoice"
        ).report_action(self)