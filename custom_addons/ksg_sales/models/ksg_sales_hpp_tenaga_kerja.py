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
        string="Peran / Posisi",
        required=True,
        tracking=True,
        help="Peran atau posisi tenaga kerja yang dibutuhkan.",
    )

    jumlah = fields.Float(
        string="Jumlah Pekerja",
        required=True,
        default=1.0,
        tracking=True,
        help="Jumlah pekerja yang dibutuhkan untuk proyek.",
    )

    currency_id = fields.Many2one(
        related="hpp_id.currency_id",
        string="Mata Uang",
        store=True,
        readonly=True,
    )

    estimasi_biaya_satuan = fields.Monetary(
        string="Estimasi Biaya / Orang (Inc. BPJS)",
        currency_field="currency_id",
        required=True,
        default=0.0,
        tracking=True,
        help="Estimasi biaya per orang termasuk BPJS.",
    )

    total_biaya = fields.Monetary(
        string="Total Biaya",
        currency_field="currency_id",
        compute="_compute_total_biaya",
        store=True,
    )

    keterangan = fields.Text(
        string="Catatan Kebutuhan",
        tracking=True,
    )

    @api.depends("jumlah", "estimasi_biaya_satuan")
    def _compute_total_biaya(self):
        for line in self:
            line.total_biaya = (
                line.jumlah * line.estimasi_biaya_satuan
            )

    @api.constrains("jumlah")
    def _check_jumlah(self):
        for line in self:
            if line.jumlah <= 0:
                raise ValidationError(
                    "Jumlah pekerja harus lebih besar dari 0."
                )

    @api.constrains("estimasi_biaya_satuan")
    def _check_estimasi_biaya_satuan(self):
        for line in self:
            if line.estimasi_biaya_satuan < 0:
                raise ValidationError(
                    "Estimasi biaya per orang tidak boleh bernilai negatif."
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