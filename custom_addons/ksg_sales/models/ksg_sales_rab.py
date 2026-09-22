from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesRab(models.Model):
    _name = "ksg.sales.rab"
    _description = "KSG Sales RAB"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    _sql_constraints = [
        (
            "ksg_sales_rab_name_unique",
            "unique(name)",
            "Nomor RAB harus unik.",
        ),
    ]
    # ==========================================================
    # IDENTITAS RAB
    # ==========================================================

    name = fields.Char(
        string="No. RAB",
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

    tanggal_rab = fields.Date(
        string="Tanggal RAB",
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

    # ==========================================================
    # STATUS
    # ==========================================================

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

    # ==========================================================
    # DETAIL RAB
    # ==========================================================

    line_ids = fields.One2many(
        comodel_name="ksg.sales.rab.line",
        inverse_name="rab_id",
        string="Detail RAB",
        copy=True,
    )

    # ==========================================================
    # TOTAL
    # ==========================================================

    total_rab = fields.Monetary(
        string="Total RAB",
        currency_field="currency_id",
        compute="_compute_total_rab",
        store=True,
    )

    # ==========================================================
    # SEQUENCE
    # ==========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "ksg.sales.rab"
                    )
                    or "New"
                )

        return super().create(vals_list)

    # ==========================================================
    # COMPUTE TOTAL RAB
    # ==========================================================

    @api.depends("line_ids.subtotal")
    def _compute_total_rab(self):
        for rab in self:
            rab.total_rab = sum(
                rab.line_ids.mapped("subtotal")
            )

    # ==========================================================
    # ACTION SUBMIT
    # ==========================================================

    def action_submit(self):
        for rab in self:
            if rab.state != "draft":
                raise ValidationError(
                    "Hanya RAB dengan status Draft yang dapat "
                    "diajukan."
                )

            if not rab.line_ids:
                raise ValidationError(
                    "RAB harus memiliki minimal satu detail."
                )

            rab.write({
                "state": "submitted",
            })

            rab.message_post(
                body=(
                    f"RAB {rab.name} telah diajukan "
                    "untuk persetujuan."
                ),
                subtype_xmlid="mail.mt_note",
            )

        return True

    # ==========================================================
    # ACTION APPROVE
    # ==========================================================

    def action_approve(self):
        for rab in self:
            if rab.state != "submitted":
                raise ValidationError(
                    "Hanya RAB dengan status Submitted yang "
                    "dapat disetujui."
                )

            rab.write({
                "state": "approved",
            })

            rab.message_post(
                body=(
                    f"RAB {rab.name} telah disetujui."
                ),
                subtype_xmlid="mail.mt_note",
            )

        return True

    # ==========================================================
    # ACTION CREATE HPP
    # ==========================================================

    def action_create_hpp(self):
        self.ensure_one()

        if self.state != "approved":
            raise ValidationError(
                "HPP hanya dapat dibuat dari RAB yang sudah Approved."
            )

        existing_hpp = self.env["ksg.sales.hpp"].search(
            [
                ("rab_id", "=", self.id),
            ],
            limit=1,
        )

        if existing_hpp:
            raise ValidationError(
                f"HPP untuk RAB {self.name} sudah tersedia."
            )

        if not self.line_ids:
            raise ValidationError(
                "RAB harus memiliki minimal satu detail "
                "sebelum dibuat menjadi HPP."
            )

        hpp = self.env["ksg.sales.hpp"].create({
            "project_id": self.project_id.id,
            "rab_id": self.id,
            "tanggal_hpp": fields.Date.context_today(self),
            "deskripsi": (
                f"HPP turunan dari RAB {self.name} "
                f"untuk proyek {self.project_id.kode_proyek}."
            ),
        })

        hpp_lines = []

        for line in self.line_ids:
            hpp_lines.append({
                "hpp_id": hpp.id,
                "sequence": line.sequence,
                "kategori": line.kategori,
                "uraian": line.uraian,
                "spesifikasi": line.spesifikasi,
                "satuan": line.satuan,
                "qty": line.qty,
                "harga_satuan": line.harga_satuan,
                "keterangan": line.keterangan,
            })

        self.env["ksg.sales.hpp.line"].create(
            hpp_lines
        )

        self.message_post(
            body=(
                f"HPP {hpp.name} berhasil dibuat "
                f"dari RAB {self.name}."
            ),
            subtype_xmlid="mail.mt_note",
        )

        return {
            "type": "ir.actions.act_window",
            "name": "HPP",
            "res_model": "ksg.sales.hpp",
            "view_mode": "form",
            "res_id": hpp.id,
            "target": "current",
        }

    # ==========================================================
    # PROTECTION RAB APPROVED
    # ==========================================================

    def write(self, vals):
        for rab in self:
            if (
                rab.state == "approved"
                and not self.env.context.get(
                    "ksg_sales_allow_approved_rab_write"
                )
            ):
                raise ValidationError(
                    "RAB yang sudah Approved tidak dapat "
                    "diubah."
                )

        return super().write(vals)

    def unlink(self):
        for rab in self:
            if rab.state == "approved":
                raise ValidationError(
                    "RAB yang sudah Approved tidak dapat "
                    "dihapus."
                )

        return super().unlink()