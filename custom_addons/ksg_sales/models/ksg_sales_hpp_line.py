from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesHppLine(models.Model):
    _name = "ksg.sales.hpp.line"
    _description = "KSG Sales HPP Detail"
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

    # =========================================================
    # IDENTITAS / KOMPONEN HPP
    # =========================================================

    bagian = fields.Char(
        string="Bagian",
        required=True,
        tracking=True,
        help="Bagian atau komponen HPP, misalnya Team Leader, CSO, Alat dan Bahan, atau Jasa.",
    )

    mk = fields.Float(
        string="MK",
        default=12.0,
        tracking=True,
        help="Masa kerja dalam bulan.",
    )

    tk = fields.Float(
        string="TK",
        default=0.0,
        tracking=True,
        help="Jumlah tenaga kerja.",
    )

    # =========================================================
    # KOMPONEN BIAYA
    # =========================================================

    currency_id = fields.Many2one(
        related="hpp_id.currency_id",
        string="Mata Uang",
        store=True,
        readonly=True,
    )

    uang_pokok = fields.Monetary(
        string="Uang Pokok",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    tunj = fields.Monetary(
        string="Tunj.",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    thr = fields.Monetary(
        string="THR",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    seragam = fields.Monetary(
        string="Seragam",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    ovh = fields.Monetary(
        string="OVH",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    sistem = fields.Monetary(
        string="Sistem",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    bpjs_tk = fields.Monetary(
        string="BPJS TK",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    bpjs_kes = fields.Monetary(
        string="BPJS KES",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    ex_pengeluaran = fields.Monetary(
        string="Ex. Pengeluaran",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    # =========================================================
    # HASIL PERHITUNGAN HPP
    # =========================================================

    jumlah_bulan = fields.Monetary(
        string="Jumlah/Bulan",
        currency_field="currency_id",
        compute="_compute_hpp",
        store=True,
    )

    hpp_tahun = fields.Monetary(
        string="HPP/Tahun",
        currency_field="currency_id",
        compute="_compute_hpp",
        store=True,
    )

    # =========================================================
    # PENAGIHAN
    # =========================================================

    tagihan_bulan = fields.Monetary(
        string="Tagihan/Bulan",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
        help="Nilai tagihan per bulan. Diinput sesuai hasil penawaran/RAB.",
    )

    tagihan_tahun = fields.Monetary(
        string="Tagihan/Tahun",
        currency_field="currency_id",
        compute="_compute_tagihan_tahun",
        store=True,
    )

    keterangan = fields.Text(
        string="Keterangan",
        tracking=True,
    )

    # =========================================================
    # COMPUTE HPP
    # =========================================================

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
        "mk",
    )
    def _compute_hpp(self):
        for line in self:
            total_bulan = (
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

            line.jumlah_bulan = total_bulan
            line.hpp_tahun = total_bulan * (line.mk or 12.0)

    # =========================================================
    # COMPUTE TAGIHAN TAHUN
    # =========================================================

    @api.depends("tagihan_bulan")
    def _compute_tagihan_tahun(self):
        for line in self:
            line.tagihan_tahun = line.tagihan_bulan * 12

    # =========================================================
    # VALIDATION
    # =========================================================

    @api.constrains(
        "mk",
        "tk",
        "uang_pokok",
        "tunj",
        "thr",
        "seragam",
        "ovh",
        "sistem",
        "bpjs_tk",
        "bpjs_kes",
        "ex_pengeluaran",
        "tagihan_bulan",
    )
    def _check_positive_values(self):
        for line in self:
            if line.mk < 0:
                raise ValidationError("MK tidak boleh bernilai negatif.")

            if line.tk < 0:
                raise ValidationError("TK tidak boleh bernilai negatif.")

            amount_fields = [
                "uang_pokok",
                "tunj",
                "thr",
                "seragam",
                "ovh",
                "sistem",
                "bpjs_tk",
                "bpjs_kes",
                "ex_pengeluaran",
                "tagihan_bulan",
            ]

            for field_name in amount_fields:
                if getattr(line, field_name) < 0:
                    raise ValidationError(
                        f"{line._fields[field_name].string} tidak boleh bernilai negatif."
                    )

    # =========================================================
    # PROTECTION AFTER APPROVAL
    # =========================================================

    def write(self, vals):
        for line in self:
            if line.hpp_id.state == "approved":
                raise ValidationError(
                    "Detail HPP tidak dapat diubah karena HPP sudah disetujui."
                )

        return super().write(vals)

    def unlink(self):
        for line in self:
            if line.hpp_id.state == "approved":
                raise ValidationError(
                    "Detail HPP tidak dapat dihapus karena HPP sudah disetujui."
                )

        return super().unlink()