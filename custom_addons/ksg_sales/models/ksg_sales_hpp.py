from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesHpp(models.Model):
    _name = "ksg.sales.hpp"
    _description = "KSG Sales HPP"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    _sql_constraints = [
        (
            "ksg_sales_hpp_name_unique",
            "unique(name)",
            "Nomor HPP harus unik.",
        ),
    ]

    # =========================================================
    # IDENTITAS HPP
    # =========================================================

    name = fields.Char(
        string="No. HPP",
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

    tanggal_hpp = fields.Date(
        string="Tanggal HPP",
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

    scope = fields.Selection(
        related="project_id.scope",
        string="Scope Proyek",
        store=True,
        readonly=True,
    )

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

    # =========================================================
    # DETAIL HPP
    # =========================================================
    #
    # Detail HPP menjadi tabel utama yang digunakan
    # untuk perhitungan HPP.
    #
    # Tabel ini bersifat common sehingga dapat digunakan
    # baik untuk proyek Operational maupun Engineering.

    line_ids = fields.One2many(
        comodel_name="ksg.sales.hpp.line",
        inverse_name="hpp_id",
        string="Detail HPP",
        copy=True,
    )

    # =========================================================
    # KEBUTUHAN OPERATIONAL
    # =========================================================

    tenaga_kerja_ids = fields.One2many(
        comodel_name="ksg.sales.hpp.tenaga.kerja",
        inverse_name="hpp_id",
        string="Kebutuhan Tenaga Kerja",
        copy=True,
    )

    perlengkapan_ids = fields.One2many(
        comodel_name="ksg.sales.hpp.perlengkapan",
        inverse_name="hpp_id",
        string="Kebutuhan Perlengkapan dan Chemical",
        copy=True,
    )

    # =========================================================
    # KEBUTUHAN ENGINEERING
    # =========================================================

    engineering_ids = fields.One2many(
        comodel_name="ksg.sales.hpp.engineering",
        inverse_name="hpp_id",
        string="Kebutuhan Engineering",
        copy=True,
    )

    # =========================================================
    # TOTAL HPP
    # =========================================================

    total_tenaga_kerja = fields.Monetary(
        string="Total Tenaga Kerja / Bulan",
        currency_field="currency_id",
        compute="_compute_total_hpp",
        store=True,
    )

    total_perlengkapan = fields.Monetary(
        string="Total Perlengkapan & Chemical / Bulan",
        currency_field="currency_id",
        compute="_compute_total_hpp",
        store=True,
    )

    total_hpp_bulanan = fields.Monetary(
        string="Total HPP / Bulan",
        currency_field="currency_id",
        compute="_compute_total_hpp",
        store=True,
    )

    total_hpp_tahunan = fields.Monetary(
        string="Total HPP / Tahun",
        currency_field="currency_id",
        compute="_compute_total_hpp",
        store=True,
    )

    total_hpp = fields.Monetary(
        string="Total HPP",
        currency_field="currency_id",
        compute="_compute_total_hpp",
        store=True,
    )

    # =========================================================
    # CREATE
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "ksg.sales.hpp"
                    )
                    or "New"
                )

        return super().create(vals_list)

    # =========================================================
    # TOTAL HPP
    # =========================================================
    #
    # Total HPP diambil dari Detail HPP.
    #
    # Detail HPP:
    # Uang Pokok
    # + Tunjangan
    # + THR
    # + Seragam
    # + OVH
    # + Sistem
    # + BPJS TK
    # + BPJS KES
    # + Ex. Pengeluaran
    #
    # = Jumlah / Bulan
    #
    # Kemudian:
    # Jumlah / Bulan x 12
    # = HPP / Tahun
    #
    # Kebutuhan Operational tidak dijumlahkan lagi
    # di sini agar tidak terjadi double counting.

    @api.depends(
        "line_ids.jumlah_bulan",
        "tenaga_kerja_ids.subtotal",
        "perlengkapan_ids.subtotal",
    )
    def _compute_total_hpp(self):
        for hpp in self:

            # -------------------------------------------------
            # Informasi kebutuhan Operational
            # -------------------------------------------------
            # Ini hanya sebagai informasi total kebutuhan,
            # bukan ditambahkan lagi ke Total HPP.

            hpp.total_tenaga_kerja = sum(
                hpp.tenaga_kerja_ids.mapped("subtotal")
            )

            hpp.total_perlengkapan = sum(
                hpp.perlengkapan_ids.mapped("subtotal")
            )

            # -------------------------------------------------
            # Total HPP berasal dari Detail HPP
            # -------------------------------------------------

            total_bulanan = sum(
                hpp.line_ids.mapped("jumlah_bulan")
            )

            hpp.total_hpp_bulanan = total_bulanan

            # Sementara menggunakan 12 bulan.
            # Nanti dapat disesuaikan dengan durasi kontrak.

            hpp.total_hpp_tahunan = total_bulanan * 12

            # Compatibility dengan field lama.

            hpp.total_hpp = hpp.total_hpp_tahunan

    # =========================================================
    # WORKFLOW
    # =========================================================

    def action_submit(self):
        for hpp in self:

            if hpp.state != "draft":
                raise ValidationError(
                    "Hanya HPP dengan status Draft yang dapat diajukan."
                )

            # -------------------------------------------------
            # Detail HPP wajib diisi untuk semua scope
            # -------------------------------------------------

            if not hpp.line_ids:
                raise ValidationError(
                    "Isi minimal satu Detail HPP sebelum "
                    "mengajukan HPP."
                )

            # -------------------------------------------------
            # Validasi tambahan untuk Operational
            # -------------------------------------------------

            if hpp.scope == "operational":
                if (
                    not hpp.tenaga_kerja_ids
                    and not hpp.perlengkapan_ids
                ):
                    raise ValidationError(
                        "Untuk HPP Operational, isi minimal satu "
                        "kebutuhan tenaga kerja atau "
                        "perlengkapan/chemical."
                    )

            hpp.write({
                "state": "submitted",
            })

            hpp.message_post(
                body=(
                    f"HPP {hpp.name} telah diajukan "
                    "untuk persetujuan."
                ),
                subtype_xmlid="mail.mt_note",
            )

        return True

    def action_approve(self):
        for hpp in self:

            if hpp.state != "submitted":
                raise ValidationError(
                    "Hanya HPP dengan status Submitted "
                    "yang dapat disetujui."
                )

            hpp.write({
                "state": "approved",
            })

            hpp.message_post(
                body=f"HPP {hpp.name} telah disetujui.",
                subtype_xmlid="mail.mt_note",
            )

        return True

    # =========================================================
    # PROTECTION AFTER APPROVAL
    # =========================================================

    def write(self, vals):
        for hpp in self:
            if hpp.state == "approved":
                raise ValidationError(
                    "HPP yang sudah Approved tidak dapat diubah."
                )

        return super().write(vals)

    def unlink(self):
        for hpp in self:
            if hpp.state == "approved":
                raise ValidationError(
                    "HPP yang sudah Approved tidak dapat dihapus."
                )

        return super().unlink()