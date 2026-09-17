from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesHppLine(models.Model):
    _name = "ksg.sales.hpp.line"
    _description = "KSG Sales HPP Line"
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

    kategori = fields.Selection(
        selection=[
            ("material", "Material"),
            ("tenaga_kerja", "Tenaga Kerja"),
            ("equipment", "Equipment"),
            ("lainnya", "Lainnya"),
        ],
        string="Kategori",
        required=True,
    )

    uraian = fields.Char(
        string="Uraian",
        required=True,
    )

    spesifikasi = fields.Char(
        string="Spesifikasi",
    )

    satuan = fields.Char(
        string="Satuan",
    )

    qty = fields.Float(
        string="Qty",
        required=True,
        default=1.0,
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
    )

    subtotal = fields.Monetary(
        string="Subtotal",
        currency_field="currency_id",
        compute="_compute_subtotal",
        store=True,
    )

    keterangan = fields.Text(
        string="Keterangan",
    )

    @api.depends("qty", "harga_satuan")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.harga_satuan

    @api.constrains("qty")
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(
                    "Qty harus lebih besar dari 0."
                )

    @api.constrains("harga_satuan")
    def _check_harga_satuan(self):
        for line in self:
            if line.harga_satuan < 0:
                raise ValidationError(
                    "Harga Satuan tidak boleh bernilai negatif."
                )

    def write(self, vals):
        for line in self:
            if (
                line.hpp_id
                and line.hpp_id.state == "approved"
            ):
                raise ValidationError(
                    "Detail HPP yang sudah Approved tidak dapat diubah."
                )

        return super().write(vals)

    def unlink(self):
        for line in self:
            if (
                line.hpp_id
                and line.hpp_id.state == "approved"
            ):
                raise ValidationError(
                    "Detail HPP yang sudah Approved tidak dapat dihapus."
                )

        return super().unlink()