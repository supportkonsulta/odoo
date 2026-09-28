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

    # =========================================================
    # DATA DASAR DARI RAB
    # =========================================================

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

    # =========================================================
    # STRUKTUR HPP OPERATIONAL
    # Mengikuti struktur HPP Operational yang sudah dibahas
    # =========================================================

    bagian = fields.Char(
        string="Bagian",
        help="Bagian atau posisi/item yang dihitung dalam HPP.",
    )

    mk = fields.Float(
        string="MK",
        default=0.0,
        help="Jumlah kebutuhan/man-month atau nilai kuantitas tenaga kerja sesuai kebutuhan perhitungan HPP.",
    )

    tk = fields.Float(
        string="TK",
        default=0.0,
        help="Jumlah tenaga kerja.",
    )

    uang_pokok = fields.Monetary(
        string="Uang Pokok",
        currency_field="currency_id",
        default=0.0,
    )

    tunj = fields.Monetary(
        string="Tunj.",
        currency_field="currency_id",
        default=0.0,
    )

    thr = fields.Monetary(
        string="THR",
        currency_field="currency_id",
        default=0.0,
    )

    seragam = fields.Monetary(
        string="Seragam",
        currency_field="currency_id",
        default=0.0,
    )

    ovh = fields.Monetary(
        string="OVH",
        currency_field="currency_id",
        default=0.0,
    )

    sistem = fields.Monetary(
        string="Sistem",
        currency_field="currency_id",
        default=0.0,
    )

    bpjs_tk = fields.Monetary(
        string="BPJS TK",
        currency_field="currency_id",
        default=0.0,
    )

    bpjs_kes = fields.Monetary(
        string="BPJS KES",
        currency_field="currency_id",
        default=0.0,
    )

    ex_pengeluaran = fields.Monetary(
        string="Ex. Pengeluaran",
        currency_field="currency_id",
        default=0.0,
    )

    jumlah_bulan = fields.Monetary(
        string="Jumlah / Bulan",
        currency_field="currency_id",
        compute="_compute_hpp_operational",
        store=True,
    )

    hpp_tahun = fields.Monetary(
        string="HPP / Tahun",
        currency_field="currency_id",
        compute="_compute_hpp_operational",
        store=True,
    )

    # =========================================================
    # COMPUTE
    # =========================================================

    @api.depends("qty", "harga_satuan")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.harga_satuan

    @api.depends(
        "uang_pokok",
        "tunj",
        "thr",
        "seragam",
        "ovh",
        "sistem",
        "bpjs_tk",
        "bpjs_kes",
        "ex_pengeluaran",
    )
    def _compute_hpp_operational(self):
        for line in self:
            line.jumlah_bulan = (
                line.uang_pokok
                + line.tunj
                + line.thr
                + line.seragam
                + line.ovh
                + line.sistem
                + line.bpjs_tk
                + line.bpjs_kes
                + line.ex_pengeluaran
            )

            # Template Operational menggunakan periode 12 bulan.
            line.hpp_tahun = line.jumlah_bulan * 12

    # =========================================================
    # VALIDATION
    # =========================================================

    @api.constrains("qty")
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(
                    "Qty harus lebih besar dari 0."
                )

    @api.constrains(
        "harga_satuan",
        "uang_pokok",
        "tunj",
        "thr",
        "seragam",
        "ovh",
        "sistem",
        "bpjs_tk",
        "bpjs_kes",
        "ex_pengeluaran",
    )
    def _check_amounts(self):
        amount_fields = [
            "harga_satuan",
            "uang_pokok",
            "tunj",
            "thr",
            "seragam",
            "ovh",
            "sistem",
            "bpjs_tk",
            "bpjs_kes",
            "ex_pengeluaran",
        ]

        for line in self:
            for field_name in amount_fields:
                if getattr(line, field_name) < 0:
                    raise ValidationError(
                        f"{line._fields[field_name].string} "
                        "tidak boleh bernilai negatif."
                    )

    # =========================================================
    # PROTECTION AFTER APPROVAL
    # =========================================================

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