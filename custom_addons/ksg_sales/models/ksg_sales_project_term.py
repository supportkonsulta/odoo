from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesProjectTerm(models.Model):
    _name = "ksg.sales.project.term"
    _description = "KSG Sales Project Term"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "no_termin, id"

    project_id = fields.Many2one(
        "ksg.sales.project",
        string="Proyek",
        required=True,
        ondelete="cascade",
        index=True,
    )

    currency_id = fields.Many2one(
        related="project_id.currency_id",
        string="Mata Uang",
        store=True,
        readonly=True,
    )

    no_termin = fields.Integer(
        string="No. Termin",
        required=True,
    )

    deskripsi = fields.Char(
        string="Deskripsi",
    )

    persentase = fields.Float(
        string="Persentase (%)",
        required=True,
    )

    syarat_progress = fields.Float(
        string="Syarat Progress (%)",
        help=(
            "Persentase progress pekerjaan yang harus dicapai "
            "sebelum termin dapat ditagihkan. "
            "Digunakan untuk sistem penagihan Per Termin."
        ),
    )

    nominal = fields.Monetary(
        string="Nominal",
        currency_field="currency_id",
        copy=False,
    )

    tanggal_jatuh_tempo = fields.Date(
        string="Tanggal Jatuh Tempo",
        required=True,
    )

    invoice_id = fields.Many2one(
        "account.move",
        string="Invoice",
        domain=[("move_type", "=", "out_invoice")],
        copy=False,
    )

    state = fields.Selection(
        [
            (
                "belum_jatuh_tempo",
                "Belum Jatuh Tempo",
            ),
            (
                "jatuh_tempo",
                "Jatuh Tempo",
            ),
            (
                "sudah_ditagih",
                "Sudah Ditagih",
            ),
        ],
        string="Status",
        compute="_compute_state",
        store=True,
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
                    "Proyek wajib dipilih untuk membuat Termin."
                )

            project = self.env["ksg.sales.project"].browse(project_id)

            if not project.exists():
                raise ValidationError(
                    "Proyek yang dipilih tidak ditemukan."
                )

            persentase = vals.get("persentase", 0.0)

            vals["nominal"] = (
                persentase / 100.0
            ) * project.nilai_kontrak_terkini

        records = super().create(vals_list)

        records._validate_term_rules()

        return records

    # ==========================================================
    # VALIDATION
    # ==========================================================

    def _validate_term_rules(self):
        """
        Validasi aturan dasar Termin.

        Validasi total 100% untuk Per Termin tidak dilakukan
        di sini karena record dapat dibuat satu per satu.

        Validasi total 100% dilakukan melalui
        action_validate_terms().
        """

        for term in self:

            if term.no_termin <= 0:
                raise ValidationError(
                    "No. Termin harus lebih besar dari 0."
                )

            if term.persentase <= 0 or term.persentase > 100:
                raise ValidationError(
                    "Persentase Termin harus lebih dari 0% "
                    "dan maksimal 100%."
                )

            if term.project_id:

                if term.project_id.sistem_penagihan == "per_termin":

                    if (
                        term.syarat_progress is False
                        or term.syarat_progress is None
                    ):
                        raise ValidationError(
                            "Syarat Progress wajib diisi "
                            "untuk sistem penagihan Per Termin."
                        )

                    if (
                        term.syarat_progress < 0
                        or term.syarat_progress > 100
                    ):
                        raise ValidationError(
                            "Syarat Progress harus berada "
                            "antara 0% sampai 100%."
                        )

    def _validate_project_term_total(self):
        """
        Validasi total persentase Termin dalam satu proyek.

        Khusus Per Termin:
        total persentase harus tepat 100%.
        """

        projects = self.mapped("project_id")

        for project in projects:

            if project.sistem_penagihan != "per_termin":
                continue

            terms = project.term_ids

            if not terms:
                raise ValidationError(
                    "Proyek dengan sistem penagihan Per Termin "
                    "wajib memiliki minimal satu Termin."
                )

            total = sum(
                terms.mapped("persentase")
            )

            if abs(total - 100.0) > 0.0001:
                raise ValidationError(
                    "Total persentase Termin untuk sistem "
                    "Per Termin harus tepat 100%. "
                    f"Total saat ini: {total:.2f}%."
                )

            for term in terms:

                if (
                    term.syarat_progress is False
                    or term.syarat_progress is None
                ):
                    raise ValidationError(
                        f"Syarat Progress pada Termin "
                        f"{term.no_termin} wajib diisi "
                        "untuk sistem penagihan Per Termin."
                    )

                if (
                    term.syarat_progress < 0
                    or term.syarat_progress > 100
                ):
                    raise ValidationError(
                        f"Syarat Progress pada Termin "
                        f"{term.no_termin} harus berada "
                        "antara 0% sampai 100%."
                    )

    # ==========================================================
    # PUBLIC VALIDATION ACTION
    # ==========================================================

    def action_validate_terms(self):
        """
        Validasi seluruh Termin dalam proyek.
        """

        projects = self.mapped("project_id")

        for project in projects:

            if not project.term_ids:
                raise ValidationError(
                    "Proyek belum memiliki Termin Penagihan."
                )

            project.term_ids._validate_term_rules()

            project.term_ids._validate_project_term_total()

        return True

    # ==========================================================
    # RECOMPUTE NOMINAL
    # ==========================================================

    def action_recompute_unbilled_nominal(
            self,
            contract_value=None,
        ):
            """
            Menghitung ulang nominal Termin yang belum ditagih.

            Termin yang sudah ditagih tidak diubah.
            Sisa nilai kontrak dialokasikan ke termin yang
            belum ditagih berdasarkan proporsi persentasenya.
            """

            for project in self.mapped("project_id"):

                # Gunakan nilai kontrak dari Addendum jika diberikan.
                current_contract_value = (
                    contract_value
                    if contract_value is not None
                    else project.nilai_kontrak_terkini
                )

                # Termin yang sudah ditagih tetap menggunakan
                # nominal sebelumnya.
                billed_terms = project.term_ids.filtered(
                    lambda term: term.state == "sudah_ditagih"
                )

                # Hanya termin yang belum ditagih yang dihitung ulang.
                unbilled_terms = project.term_ids.filtered(
                    lambda term: term.state != "sudah_ditagih"
                )

                if not unbilled_terms:
                    continue

                # Total nominal yang sudah ditagih.
                total_billed = sum(
                    billed_terms.mapped("nominal")
                )

                # Sisa nilai kontrak yang harus dialokasikan
                # ke termin yang belum ditagih.
                remaining_value = (
                    current_contract_value - total_billed
                )

                # Total persentase termin yang belum ditagih.
                total_unbilled_percentage = sum(
                    unbilled_terms.mapped("persentase")
                )

                if total_unbilled_percentage <= 0:
                    continue

                # Alokasikan sisa nilai kontrak berdasarkan
                # proporsi persentase masing-masing termin.
                for term in unbilled_terms:
                    term.nominal = (
                        term.persentase
                        / total_unbilled_percentage
                    ) * remaining_value

            return True
    # ==========================================================
    # CREATE INVOICE
    # ==========================================================

    def action_create_invoice(self):
        """
        Membuat Customer Invoice Odoo dari Termin Penagihan.

        Invoice dibuat dalam kondisi Draft.

        Setelah invoice di-post oleh user,
        state Termin otomatis berubah menjadi
        Sudah Ditagih.
        """

        for term in self:

            # --------------------------------------------------
            # VALIDASI DASAR
            # --------------------------------------------------

            if term.invoice_id:
                raise ValidationError(
                    f"Termin {term.no_termin} sudah memiliki Invoice."
                )

            if not term.project_id:
                raise ValidationError(
                    "Termin harus memiliki Proyek."
                )

            if term.state == "sudah_ditagih":
                raise ValidationError(
                    "Termin yang sudah ditagih tidak dapat "
                    "dibuatkan Invoice lagi."
                )

            # --------------------------------------------------
            # VALIDASI KHUSUS PER TERMIN
            # --------------------------------------------------

            if term.project_id.sistem_penagihan == "per_termin":

                term.project_id.term_ids._validate_project_term_total()

                if (
                    term.syarat_progress is False
                    or term.syarat_progress is None
                ):
                    raise ValidationError(
                        f"Syarat Progress pada Termin "
                        f"{term.no_termin} wajib diisi "
                        "sebelum membuat Invoice."
                    )

            # --------------------------------------------------
            # VALIDASI NOMINAL
            # --------------------------------------------------

            if term.nominal <= 0:
                raise ValidationError(
                    "Nominal Termin harus lebih besar dari 0."
                )

            # --------------------------------------------------
            # CUSTOMER
            # --------------------------------------------------

            partner = term.project_id.klien

            if not partner:
                raise ValidationError(
                    "Klien / Perusahaan pada Proyek belum diisi."
                )

            # --------------------------------------------------
            # VALIDASI RECEIVABLE CUSTOMER
            # --------------------------------------------------

            receivable_account = (
                partner.property_account_receivable_id
            )

            if not receivable_account:
                raise ValidationError(
                    f"Customer '{partner.display_name}' belum memiliki "
                    "Akun Piutang (Receivable). "
                    "Silakan konfigurasi Akun Piutang pada customer "
                    "tersebut terlebih dahulu."
                )

            # --------------------------------------------------
            # CARI AKUN PENDAPATAN
            # --------------------------------------------------

            income_account = self.env["account.account"].search(
                [
                    (
                        "company_ids",
                        "in",
                        self.env.company.id,
                    ),
                    (
                        "account_type",
                        "in",
                        [
                            "income",
                            "income_other",
                        ],
                    ),
                ],
                limit=1,
            )

            if not income_account:
                raise ValidationError(
                    "Akun pendapatan belum tersedia. "
                    "Silakan konfigurasi akun pendapatan "
                    "terlebih dahulu."
                )

            # --------------------------------------------------
            # CARI SALES JOURNAL
            # --------------------------------------------------

            sales_journal = self.env["account.journal"].search(
                [
                    (
                        "type",
                        "=",
                        "sale",
                    ),
                    (
                        "company_id",
                        "=",
                        self.env.company.id,
                    ),
                ],
                limit=1,
            )

            if not sales_journal:
                raise ValidationError(
                    "Sales Journal belum tersedia untuk perusahaan "
                    f"'{self.env.company.display_name}'."
                )

            # --------------------------------------------------
            # REFERENSI INVOICE
            # --------------------------------------------------

            project_code = (
                term.project_id.kode_proyek
                or term.project_id.display_name
            )

            invoice_reference = (
                f"{project_code} - "
                f"Termin {term.no_termin}"
            )

            # --------------------------------------------------
            # DESKRIPSI INVOICE
            # --------------------------------------------------

            invoice_line_name = (
                f"{term.project_id.nama_pekerjaan} - "
                f"Termin {term.no_termin}: "
                f"{term.deskripsi or 'Penagihan Termin'}"
            )

            # --------------------------------------------------
            # CREATE ACCOUNT.MOVE
            # --------------------------------------------------

            invoice_vals = {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "journal_id": sales_journal.id,
                "invoice_date": fields.Date.context_today(self),
                "invoice_date_due": term.tanggal_jatuh_tempo,
                "ref": invoice_reference,
                "ksg_term_id": term.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": invoice_line_name,
                            "quantity": 1.0,
                            "price_unit": term.nominal,
                            "account_id": income_account.id,
                        },
                    )
                ],
            }

            invoice = self.env["account.move"].create(
                invoice_vals
            )

            # --------------------------------------------------
            # HUBUNGKAN INVOICE KE TERMIN
            # --------------------------------------------------

            term.invoice_id = invoice.id

            # --------------------------------------------------
            # CHATTER
            # --------------------------------------------------

            term.message_post(
                body=(
                    f"Invoice <b>{invoice.name or 'Draft'}</b> "
                    f"berhasil dibuat untuk Termin "
                    f"{term.no_termin}."
                )
            )

        return True

    # ==========================================================
    # OPEN INVOICE
    # ==========================================================

    def action_open_invoice(self):
        """
        Membuka Invoice yang terhubung dengan Termin.
        """

        self.ensure_one()

        if not self.invoice_id:
            raise ValidationError(
                "Termin ini belum memiliki Invoice."
            )

        return {
            "type": "ir.actions.act_window",
            "name": "Customer Invoice",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.invoice_id.id,
            "target": "current",
        }

    # ==========================================================
    # COMPUTE STATE
    # ==========================================================

    @api.depends(
        "invoice_id",
        "invoice_id.state",
        "tanggal_jatuh_tempo",
    )
    def _compute_state(self):

        today = fields.Date.context_today(self)

        for term in self:

            if (
                term.invoice_id
                and term.invoice_id.state == "posted"
            ):
                term.state = "sudah_ditagih"

            elif (
                term.tanggal_jatuh_tempo
                and term.tanggal_jatuh_tempo < today
            ):
                term.state = "jatuh_tempo"

            else:
                term.state = "belum_jatuh_tempo"

    # ==========================================================
    # CONSTRAINT - NO TERMIN
    # ==========================================================

    @api.constrains("no_termin")
    def _check_no_termin(self):

        for term in self:

            if term.no_termin <= 0:
                raise ValidationError(
                    "No. Termin harus lebih besar dari 0."
                )

    # ==========================================================
    # CONSTRAINT - PERSENTASE
    # ==========================================================

    @api.constrains("persentase")
    def _check_persentase(self):

        for term in self:

            if (
                term.persentase <= 0
                or term.persentase > 100
            ):
                raise ValidationError(
                    "Persentase Termin harus lebih dari 0% "
                    "dan maksimal 100%."
                )

    # ==========================================================
    # CONSTRAINT - TOTAL MAKSIMAL
    # ==========================================================

    @api.constrains(
        "project_id",
        "persentase",
    )
    def _check_total_persentase(self):
        """
        Untuk semua sistem penagihan, total Termin tidak boleh
        melebihi 100%.

        Khusus Per Termin, pengecekan tepat 100% dilakukan
        melalui action_validate_terms().
        """

        for term in self:

            if not term.project_id:
                continue

            total = sum(
                term.project_id.term_ids.mapped(
                    "persentase"
                )
            )

            if total > 100.0001:
                raise ValidationError(
                    "Total persentase seluruh Termin dalam "
                    "satu proyek tidak boleh lebih dari 100%."
                )

    # ==========================================================
    # CONSTRAINT - SYARAT PROGRESS
    # ==========================================================

    @api.constrains(
        "syarat_progress",
        "project_id",
    )
    def _check_syarat_progress(self):

        for term in self:

            if not term.project_id:
                continue

            if (
                term.project_id.sistem_penagihan
                != "per_termin"
            ):
                continue

            if (
                term.syarat_progress is not False
                and term.syarat_progress is not None
            ):

                if (
                    term.syarat_progress < 0
                    or term.syarat_progress > 100
                ):
                    raise ValidationError(
                        "Syarat Progress harus berada "
                        "antara 0% sampai 100%."
                    )

    # ==========================================================
    # WRITE
    # ==========================================================

    def write(self, vals):

        # Termin yang sudah ditagih tidak boleh mengubah
        # persentasenya.
        if "persentase" in vals:

            for term in self:

                if term.state == "sudah_ditagih":
                    raise ValidationError(
                        "Termin yang sudah ditagih "
                        "tidak dapat mengubah persentase."
                    )

        result = super().write(vals)

        # Jika persentase berubah, nominal Termin yang belum
        # ditagih harus dihitung ulang.
        if "persentase" in vals:
            self.action_recompute_unbilled_nominal()

        # Jika data terkait Per Termin berubah,
        # validasi aturan dasarnya.
        if (
            "persentase" in vals
            or "syarat_progress" in vals
            or "project_id" in vals
        ):
            self._validate_term_rules()

        return result

    # ==========================================================
    # UNLINK
    # ==========================================================

    def unlink(self):

        for term in self:

            if term.state == "sudah_ditagih":
                raise ValidationError(
                    "Termin yang sudah ditagih "
                    "tidak dapat dihapus."
                )

        return super().unlink()