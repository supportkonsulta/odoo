from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesHppPerlengkapan(models.Model):
    _name = "ksg.sales.hpp.perlengkapan"
    _description = "KSG Sales HPP Perlengkapan dan Chemical"
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

    item = fields.Char(
        string="Nama Barang / Alat",
        required=True,
        tracking=True,
        help="Nama barang, alat, perlengkapan, atau chemical yang dibutuhkan.",
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

    keterangan = fields.Text(
        string="Keterangan",
        tracking=True,
    )

    @api.constrains("jumlah")
    def _check_jumlah(self):
        for line in self:
            if line.jumlah <= 0:
                raise ValidationError(
                    "Jumlah perlengkapan/chemical harus lebih besar dari 0."
                )

    def write(self, vals):
        for line in self:
            if (
                line.hpp_id
                and line.hpp_id.state == "approved"
            ):
                raise ValidationError(
                    "Detail perlengkapan/chemical pada HPP "
                    "yang sudah Approved tidak dapat diubah."
                )

        return super().write(vals)

    def unlink(self):
        for line in self:
            if (
                line.hpp_id
                and line.hpp_id.state == "approved"
            ):
                raise ValidationError(
                    "Detail perlengkapan/chemical pada HPP "
                    "yang sudah Approved tidak dapat dihapus."
                )

        return super().unlink()