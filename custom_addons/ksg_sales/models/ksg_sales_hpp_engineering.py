from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesHppEngineering(models.Model):
    _name = "ksg.sales.hpp.engineering"
    _description = "KSG Sales HPP Engineering"
    _order = "sequence, id"

    # =========================================================
    # RELASI HPP
    # =========================================================

    hpp_id = fields.Many2one(
        comodel_name="ksg.sales.hpp",
        string="HPP",
        required=True,
        ondelete="cascade",
        index=True,
    )

    # =========================================================
    # DATA ENGINEERING
    # =========================================================

    sequence = fields.Integer(
        string="No.",
        default=10,
    )

    uraian = fields.Char(
        string="Uraian",
        required=True,
        tracking=True,
        help="Nama kebutuhan atau pekerjaan Engineering.",
    )

    spesifikasi = fields.Char(
        string="Spesifikasi",
        tracking=True,
        help="Spesifikasi atau detail kebutuhan Engineering.",
    )

    satuan = fields.Char(
        string="Satuan",
        tracking=True,
        help="Satuan kebutuhan, misalnya Unit, Lot, Hari, Meter, dan sebagainya.",
    )

    qty = fields.Float(
        string="Qty",
        required=True,
        default=1.0,
        tracking=True,
    )

    currency_id = fields.Many2one(
        related="hpp_id.currency_id",
        string="Mata Uang",
        store=True,
        readonly=True,
    )

    harga_satuan = fields.Monetary(
        string="Harga Satuan",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
        help="Harga satuan kebutuhan Engineering.",
    )

    subtotal = fields.Monetary(
        string="Subtotal",
        currency_field="currency_id",
        compute="_compute_subtotal",
        store=True,
    )

    keterangan = fields.Text(
        string="Keterangan",
        tracking=True,
    )

    # =========================================================
    # COMPUTE SUBTOTAL
    # =========================================================

    @api.depends("qty", "harga_satuan")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.harga_satuan

    # =========================================================
    # VALIDATION
    # =========================================================

    @api.constrains("qty")
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(
                    "Qty kebutuhan Engineering harus lebih besar dari 0."
                )

    @api.constrains("harga_satuan")
    def _check_harga_satuan(self):
        for line in self:
            if line.harga_satuan < 0:
                raise ValidationError(
                    "Harga satuan kebutuhan Engineering "
                    "tidak boleh bernilai negatif."
                )

    # =========================================================
    # PROTECTION AFTER APPROVAL
    # =========================================================

    def write(self, vals):
        for line in self:
            if line.hpp_id and line.hpp_id.state == "approved":
                raise ValidationError(
                    "Kebutuhan Engineering pada HPP yang sudah "
                    "Approved tidak dapat diubah."
                )

        return super().write(vals)

    def unlink(self):
        for line in self:
            if line.hpp_id and line.hpp_id.state == "approved":
                raise ValidationError(
                    "Kebutuhan Engineering pada HPP yang sudah "
                    "Approved tidak dapat dihapus."
                )

        return super().unlink()