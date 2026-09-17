from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class KsgSalesProjectAddendum(models.Model):
    _name = "ksg.sales.project.addendum"
    _description = "KSG Sales Project Addendum"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    # ==========================================================
    # RELASI PROYEK
    # ==========================================================

    project_id = fields.Many2one(
        comodel_name="ksg.sales.project",
        string="Proyek",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    # ==========================================================
    # NILAI KONTRAK
    # ==========================================================

    currency_id = fields.Many2one(
        related="project_id.currency_id",
        string="Mata Uang",
        store=True,
        readonly=True,
    )

    nilai_awal = fields.Monetary(
        string="Nilai Kontrak Sebelumnya",
        currency_field="currency_id",
        required=True,
        readonly=True,
        tracking=True,
    )

    nilai_kontrak_baru = fields.Monetary(
        string="Nilai Kontrak Baru",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )

    # ==========================================================
    # INFORMASI PERUBAHAN
    # ==========================================================

    tanggal_perubahan = fields.Date(
        string="Tanggal Perubahan",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    kategori_alasan = fields.Selection(
        selection=[
            ("perubahan_scope", "Perubahan Scope Pekerjaan"),
            ("perubahan_volume", "Perubahan Volume Pekerjaan"),
            ("perubahan_harga", "Perubahan Harga"),
            ("perpanjangan", "Perpanjangan Kontrak"),
            ("pengurangan", "Pengurangan Pekerjaan"),
            ("lainnya", "Lainnya"),
        ],
        string="Kategori Alasan",
        required=True,
        tracking=True,
    )

    catatan = fields.Text(
        string="Catatan",
        tracking=True,
    )

    # ==========================================================
    # STATUS APPROVAL
    # ==========================================================

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("waiting_approval", "Menunggu Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        required=True,
        default="draft",
        tracking=True,
    )

    # ==========================================================
    # CREATE
    # ==========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            project_id = vals.get("project_id")

            if not project_id:
                raise ValidationError(
                    "Proyek wajib dipilih untuk membuat Addendum."
                )

            project = self.env["ksg.sales.project"].browse(project_id)

            if not project.exists():
                raise ValidationError(
                    "Proyek yang dipilih tidak ditemukan."
                )

            # Snapshot nilai kontrak saat Addendum dibuat.
            vals["nilai_awal"] = project.nilai_kontrak_terkini

        return super().create(vals_list)

    # ==========================================================
    # VALIDASI NILAI KONTRAK
    # ==========================================================

    @api.constrains("nilai_kontrak_baru", "nilai_awal")
    def _check_nilai_kontrak(self):
        for addendum in self:
            if addendum.nilai_kontrak_baru < 0:
                raise ValidationError(
                    "Nilai Kontrak Baru tidak boleh bernilai negatif."
                )

            if addendum.nilai_kontrak_baru == addendum.nilai_awal:
                raise ValidationError(
                    "Nilai Kontrak Baru harus berbeda dari "
                    "Nilai Kontrak Sebelumnya."
                )

    # ==========================================================
    # VALIDASI TANGGAL
    # ==========================================================

    @api.constrains("tanggal_perubahan")
    def _check_tanggal_perubahan(self):
        for addendum in self:
            if (
                addendum.project_id
                and addendum.project_id.tanggal_po_diterima
                and addendum.tanggal_perubahan
                < addendum.project_id.tanggal_po_diterima
            ):
                raise ValidationError(
                    "Tanggal Perubahan tidak boleh lebih kecil "
                    "dari Tanggal PO Diterima."
                )

    # ==========================================================
    # AJUKAN APPROVAL
    # ==========================================================

    def action_submit_approval(self):
        manager_group = self.env.ref(
            "ksg_sales.group_sales_manager",
            raise_if_not_found=False,
        )

        if not manager_group:
            raise UserError(
                "Group Sales Manager tidak ditemukan."
            )

        # Odoo 19:
        # Ambil user yang memiliki group Sales Manager
        # melalui relasi group_ids, bukan manager_group.users.
        managers = self.env["res.users"].search(
            [
                ("group_ids", "in", manager_group.id),
                ("active", "=", True),
            ]
        )

        if not managers:
            raise UserError(
                "Belum ada user aktif yang memiliki role Sales Manager."
            )

        for addendum in self:
            if addendum.state != "draft":
                raise UserError(
                    "Hanya Addendum dengan status Draft "
                    "yang dapat diajukan."
                )

            if not addendum.env.user.has_group(
                "ksg_sales.group_sales_user"
            ):
                raise UserError(
                    "Anda tidak memiliki akses untuk mengajukan "
                    "approval Addendum."
                )

            # Ubah status menjadi Menunggu Approval.
            addendum.write(
                {
                    "state": "waiting_approval",
                }
            )

            # Buat activity untuk setiap Sales Manager.
            for manager in managers:
                addendum.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=manager.id,
                    summary="Approval Addendum Kontrak",
                    note=(
                        "Terdapat Addendum Kontrak yang membutuhkan "
                        "persetujuan untuk proyek "
                        f"{addendum.project_id.kode_proyek}."
                    ),
                )

        return True

    # ==========================================================
    # APPROVE
    # ==========================================================

    def action_approve(self):
        for addendum in self:
            if addendum.state != "waiting_approval":
                raise UserError(
                    "Hanya Addendum dengan status "
                    "'Menunggu Approval' yang dapat disetujui."
                )

            if not addendum.env.user.has_group(
                "ksg_sales.group_sales_manager"
            ):
                raise UserError(
                    "Hanya Sales Manager yang dapat menyetujui "
                    "Addendum."
                )

            # ==================================================
            # APPROVE ADDENDUM
            # ==================================================

            # Nilai kontrak terkini pada Project merupakan
            # computed field yang mengambil nilai dari
            # Addendum Approved terakhir.
            addendum.write(
                {
                    "state": "approved",
                }
            )

            project = addendum.project_id

            project.term_ids.action_recompute_unbilled_nominal(
                    contract_value=addendum.nilai_kontrak_baru
                )

            project.message_post(
                body=(
                    f"Addendum disetujui. Nilai kontrak berubah dari "
                    f"{addendum.nilai_awal:,.2f} menjadi "
                    f"{addendum.nilai_kontrak_baru:,.2f}."
                ),
                subtype_xmlid="mail.mt_note",
                )

        return True

    # ==========================================================
    # REJECT
    # ==========================================================

    def action_reject(self):
        for addendum in self:
            if addendum.state != "waiting_approval":
                raise UserError(
                    "Hanya Addendum dengan status "
                    "'Menunggu Approval' yang dapat ditolak."
                )

            if not addendum.env.user.has_group(
                "ksg_sales.group_sales_manager"
            ):
                raise UserError(
                    "Hanya Sales Manager yang dapat menolak "
                    "Addendum."
                )

            addendum.write(
                {
                    "state": "rejected",
                }
            )

        return True

    # ==========================================================
    # APPEND-ONLY
    # ==========================================================

    def write(self, vals):
        protected_states = {
            "approved",
        }

        for addendum in self:
            if (
                addendum.state in protected_states
                and not self.env.context.get(
                    "ksg_sales_allow_approved_write"
                )
            ):
                raise UserError(
                    "Addendum yang sudah Approved tidak dapat diubah."
                )

        return super().write(vals)

    def unlink(self):
        for addendum in self:
            if addendum.state == "approved":
                raise UserError(
                    "Addendum yang sudah Approved tidak dapat dihapus."
                )

        return super().unlink()