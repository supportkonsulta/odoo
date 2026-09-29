from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesHppPerlengkapan(models.Model):
    _name = "ksg.sales.hpp.perlengkapan"
    _description = "KSG Sales HPP Perlengkapan dan Chemical"
    _order = "sequence, id"

    hpp_id = fields.Many2one(
        "ksg.sales.hpp",
        string="HPP",
        required=True,
        ondelete="cascade",
        index=True,
    )

    sequence = fields.Integer(
        string="No.",
        default=10,
    )

    # ==========================================================
    # DETAIL PERLENGKAPAN & CHEMICAL
    # ==========================================================

    item = fields.Char(
        string="Nama Barang/Perlengkapan",
        required=True,
        tracking=True,
    )

    spesifikasi = fields.Char(
        string="Spesifikasi",
        tracking=True,
    )

    satuan = fields.Char(
        string="Satuan",
        required=True,
        default="Unit",
        tracking=True,
    )

    jumlah = fields.Float(
        string="Jumlah",
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
        required=True,
        default=0.0,
        tracking=True,
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

    # ==========================================================
    # COMPUTE
    # ==========================================================

    @api.depends("jumlah", "harga_satuan")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (
                line.jumlah * line.harga_satuan
            )

    # ==========================================================
    # VALIDATION
    # ==========================================================

    @api.constrains("jumlah")
    def _check_jumlah(self):
        for line in self:
            if line.jumlah <= 0:
                raise ValidationError(
                    "Jumlah perlengkapan/chemical harus lebih besar "
                    "dari 0."
                )

    @api.constrains("harga_satuan")
    def _check_harga_satuan(self):
        for line in self:
            if line.harga_satuan < 0:
                raise ValidationError(
                    "Harga satuan tidak boleh negatif."
                )

    # ==========================================================
    # PROTECTION AFTER APPROVED
    # ==========================================================

    def write(self, vals):
        for line in self:
            if line.hpp_id and line.hpp_id.state == "approved":
                raise ValidationError(
                    "Detail perlengkapan/chemical pada HPP "
                    "yang sudah Approved tidak dapat diubah."
                )
        return super().write(vals)

    def unlink(self):
        for line in self:
            if line.hpp_id and line.hpp_id.state == "approved":
                raise ValidationError(
                    "Detail perlengkapan/chemical pada HPP "
                    "yang sudah Approved tidak dapat dihapus."
                )
        return super().unlink()