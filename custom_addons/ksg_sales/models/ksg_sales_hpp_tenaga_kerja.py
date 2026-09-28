from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesHppTenagaKerja(models.Model):
    _name = "ksg.sales.hpp.tenaga.kerja"
    _description = "KSG Sales HPP Tenaga Kerja"
    _order = "sequence, id"

    hpp_id = fields.Many2one(
        comodel_name="ksg.sales.hpp",
        string="HPP",
        required=True,
        ondelete="cascade",
        index=True,
    )

    sequence = fields.Integer(
        string="No.",
        default=10,
    )

    posisi = fields.Char(
        string="Posisi",
        required=True,
        tracking=True,
        help="Posisi tenaga kerja yang dibutuhkan.",
    )

    jumlah = fields.Float(
        string="Jumlah",
        required=True,
        default=1.0,
        tracking=True,
        help="Jumlah tenaga kerja yang dibutuhkan.",
    )

    satuan = fields.Char(
        string="Satuan",
        default="Orang",
        tracking=True,
    )

    currency_id = fields.Many2one(
        related="hpp_id.currency_id",
        string="Mata Uang",
        store=True,
        readonly=True,
    )

    harga = fields.Monetary(
        string="Harga",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
        help="Harga diisi oleh Operational.",
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

    @api.depends("jumlah", "harga")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.jumlah * line.harga

    @api.constrains("jumlah")
    def _check_jumlah(self):
        for line in self:
            if line.jumlah <= 0:
                raise ValidationError(
                    "Jumlah tenaga kerja harus lebih besar dari 0."
                )

    @api.constrains("harga")
    def _check_harga(self):
        for line in self:
            if line.harga < 0:
                raise ValidationError(
                    "Harga tenaga kerja tidak boleh bernilai negatif."
                )

    def write(self, vals):
        for line in self:
            if (
                line.hpp_id
                and line.hpp_id.state == "approved"
            ):
                raise ValidationError(
                    "Detail tenaga kerja pada HPP yang sudah "
                    "Approved tidak dapat diubah."
                )

        return super().write(vals)

    def unlink(self):
        for line in self:
            if (
                line.hpp_id
                and line.hpp_id.state == "approved"
            ):
                raise ValidationError(
                    "Detail tenaga kerja pada HPP yang sudah "
                    "Approved tidak dapat dihapus."
                )

        return super().unlink()