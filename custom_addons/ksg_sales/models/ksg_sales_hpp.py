from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesHpp(models.Model):
    _name = "ksg.sales.hpp"
    _description = "KSG Sales HPP"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    _sql_constraints = [
        (
            "ksg_sales_hpp_name_unique",
            "unique(name)",
            "Nomor HPP harus unik.",
        ),
    ]

    name = fields.Char(
        string="No. HPP",
        required=True,
        copy=False,
        default="New",
        tracking=True,
    )

    project_id = fields.Many2one(
        comodel_name="ksg.sales.project",
        string="Proyek",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    rab_id = fields.Many2one(
        comodel_name="ksg.sales.rab",
        string="RAB",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    tanggal_hpp = fields.Date(
        string="Tanggal HPP",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    deskripsi = fields.Text(
        string="Deskripsi",
        tracking=True,
    )

    currency_id = fields.Many2one(
        related="project_id.currency_id",
        string="Mata Uang",
        store=True,
        readonly=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
        ],
        string="Status",
        required=True,
        default="draft",
        tracking=True,
    )

    line_ids = fields.One2many(
        comodel_name="ksg.sales.hpp.line",
        inverse_name="hpp_id",
        string="Detail HPP",
        copy=True,
    )

    total_hpp = fields.Monetary(
        string="Total HPP",
        currency_field="currency_id",
        compute="_compute_total_hpp",
        store=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("ksg.sales.hpp")
                    or "New"
                )

        return super().create(vals_list)

    @api.onchange("rab_id")
    def _onchange_rab_id(self):
        if self.rab_id:
            self.project_id = self.rab_id.project_id

    @api.depends("line_ids.subtotal")
    def _compute_total_hpp(self):
        for hpp in self:
            hpp.total_hpp = sum(
                hpp.line_ids.mapped("subtotal")
            )

    def action_submit(self):
        for hpp in self:
            if hpp.state != "draft":
                raise ValidationError(
                    "Hanya HPP dengan status Draft yang dapat diajukan."
                )

            if not hpp.line_ids:
                raise ValidationError(
                    "HPP harus memiliki minimal satu detail."
                )

            hpp.write({
                "state": "submitted",
            })

            hpp.message_post(
                body=f"HPP {hpp.name} telah diajukan untuk persetujuan.",
                subtype_xmlid="mail.mt_note",
            )

        return True

    def action_approve(self):
        for hpp in self:
            if hpp.state != "submitted":
                raise ValidationError(
                    "Hanya HPP dengan status Submitted yang dapat disetujui."
                )

            hpp.write({
                "state": "approved",
            })

            hpp.message_post(
                body=f"HPP {hpp.name} telah disetujui.",
                subtype_xmlid="mail.mt_note",
            )

        return True

    def write(self, vals):
        for hpp in self:
            if hpp.state == "approved":
                raise ValidationError(
                    "HPP yang sudah Approved tidak dapat diubah."
                )

        return super().write(vals)

    def unlink(self):
        for hpp in self:
            if hpp.state == "approved":
                raise ValidationError(
                    "HPP yang sudah Approved tidak dapat dihapus."
                )

        return super().unlink()