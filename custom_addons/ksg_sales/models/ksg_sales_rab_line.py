from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesRabLine(models.Model):
    _name = "ksg.sales.rab.line"
    _description = "KSG Sales RAB Line"
    _order = "sequence, id"

    # ==========================================================
    # RELASI RAB
    # ==========================================================

    rab_id = fields.Many2one(
        comodel_name="ksg.sales.rab",
        string="RAB",
        required=True,
        ondelete="cascade",
        index=True,
    )

    # ==========================================================
    # INFORMASI ITEM
    # ==========================================================

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
        default="material",
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
        related="rab_id.currency_id",
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

    # ==========================================================
    # COMPUTE SUBTOTAL
    # ==========================================================

    @api.depends(
        "qty",
        "harga_satuan",
    )
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (
                line.qty * line.harga_satuan
            )

    # ==========================================================
    # VALIDASI QTY
    # ==========================================================

    @api.constrains("qty")
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(
                    "Qty harus lebih besar dari 0."
                )

    # ==========================================================
    # VALIDASI HARGA
    # ==========================================================

    @api.constrains("harga_satuan")
    def _check_harga_satuan(self):
        for line in self:
            if line.harga_satuan < 0:
                raise ValidationError(
                    "Harga Satuan tidak boleh bernilai negatif."
                )

    # ==========================================================
    # PROTECTION RAB APPROVED
    # ==========================================================

    def write(self, vals):
        for line in self:
            if (
                line.rab_id
                and line.rab_id.state == "approved"
            ):
                raise ValidationError(
                    "Detail RAB yang sudah Approved tidak "
                    "dapat diubah."
                )

        return super().write(vals)

    def unlink(self):
        for line in self:
            if (
                line.rab_id
                and line.rab_id.state == "approved"
            ):
                raise ValidationError(
                    "Detail RAB yang sudah Approved tidak "
                    "dapat dihapus."
                )

        return super().unlink()