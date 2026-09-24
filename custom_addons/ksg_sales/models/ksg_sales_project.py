from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KsgSalesProject(models.Model):
    _name = "ksg.sales.project"
    _description = "KSG Sales Project"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _rec_name = "kode_proyek"

    _sql_constraints = [
        (
            "kode_proyek_unique",
            "unique(kode_proyek)",
            "Kode Proyek harus unik.",
        ),
    ]

    # =========================================================
    # IDENTITAS PROYEK
    # =========================================================

    kode_proyek = fields.Char(
        string="Kode Proyek",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )

    klien = fields.Many2one(
        comodel_name="res.partner",
        string="Klien / Perusahaan",
        required=True,
        tracking=True,
    )

    kategori = fields.Many2one(
        comodel_name="ksg.sales.category",
        string="Kategori",
        required=True,
        tracking=True,
    )

    status = fields.Selection(
        selection=[
            ("aktif", "Aktif"),
            ("selesai", "Selesai"),
            ("batal", "Batal"),
        ],
        string="Status",
        required=True,
        default="aktif",
        tracking=True,
    )

    nama_pekerjaan = fields.Char(
        string="Nama Pekerjaan",
        required=True,
        size=250,
        tracking=True,
    )

    # =========================================================
    # SCOPE PROYEK
    # =========================================================

    scope_engineering = fields.Boolean(
        string="Engineering",
        default=False,
        tracking=True,
        help=(
            "Centang jika proyek ini membutuhkan proses "
            "atau pekerjaan dalam scope Engineering."
        ),
    )

    scope_operational = fields.Boolean(
        string="Operational",
        default=False,
        tracking=True,
        help=(
            "Centang jika proyek ini membutuhkan proses "
            "atau pekerjaan dalam scope Operational."
        ),
    )

    # =========================================================
    # DOKUMEN & KONTRAK
    # =========================================================

    tanggal_po_diterima = fields.Date(
        string="Tanggal PO Diterima",
        required=True,
        tracking=True,
    )

    no_pk = fields.Char(
        string="PK / No. PK / PO",
        required=True,
        tracking=True,
        help=(
            "Nomor PK/PO sesuai dokumen dari klien. "
            "Format dapat berbeda-beda sesuai surat klien."
        ),
    )

    awal_kontrak = fields.Date(
        string="Awal Kontrak",
        required=True,
        tracking=True,
    )

    akhir_kontrak = fields.Date(
        string="Akhir Kontrak",
        required=True,
        tracking=True,
    )

    # =========================================================
    # NILAI KONTRAK
    # =========================================================

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Mata Uang",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    nilai_kontrak_awal = fields.Monetary(
        string="Nilai Kontrak",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )

    nilai_kontrak_terkini = fields.Monetary(
        string="Nilai Kontrak Terkini",
        currency_field="currency_id",
        compute="_compute_nilai_kontrak_terkini",
        store=True,
        tracking=True,
    )

    sisa_nilai_kontrak = fields.Monetary(
        string="Sisa Nilai Kontrak",
        currency_field="currency_id",
        compute="_compute_sisa_nilai_kontrak",
        store=True,
        tracking=True,
    )

    # =========================================================
    # ADDENDUM
    # =========================================================

    addendum_ids = fields.One2many(
        comodel_name="ksg.sales.project.addendum",
        inverse_name="project_id",
        string="Addendum Kontrak",
    )

    # =========================================================
    # RAB
    # =========================================================

    rab_ids = fields.One2many(
        comodel_name="ksg.sales.rab",
        inverse_name="project_id",
        string="RAB",
    )

    # =========================================================
    # HPP
    # =========================================================

    hpp_ids = fields.One2many(
        "ksg.sales.hpp",
        "project_id",
        string="HPP",
    )

    # =========================================================
    # TERMIN PENAGIHAN
    # =========================================================

    term_ids = fields.One2many(
        comodel_name="ksg.sales.project.term",
        inverse_name="project_id",
        string="Termin Penagihan",
    )

    # =========================================================
    # CHECKLIST ENGINEERING
    # =========================================================

    checklist_dokumen_ids = fields.One2many(
        comodel_name="ksg.sales.project.checklist",
        inverse_name="project_id",
        string="Checklist Dokumen Engineering",
    )

    # =========================================================
    # PENAGIHAN
    # =========================================================

    sistem_penagihan = fields.Selection(
        selection=[
            ("per_bulan", "Per Bulan"),
            ("per_3_bulan", "Per 3 Bulan"),
            ("per_termin", "Per Termin"),
            ("pelunasan_100", "Pelunasan 100%"),
        ],
        string="Termin Penagihan",
        required=True,
        tracking=True,
    )

    # =========================================================
    # KETERANGAN
    # =========================================================

    keterangan = fields.Text(
        string="Keterangan",
    )

    # =========================================================
    # CREATE
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("kode_proyek"):
                vals["kode_proyek"] = (
                    self.env["ir.sequence"].next_by_code(
                        "ksg.sales.project"
                    )
                    or "/"
                )

        return super().create(vals_list)

    # =========================================================
    # ONCHANGE KATEGORI
    # =========================================================

    @api.onchange("kategori")
    def _onchange_kategori(self):
        if not self.kategori:
            self.checklist_dokumen_ids = [(5, 0, 0)]
            return

        self.checklist_dokumen_ids = [
            (
                0,
                0,
                {
                    "checklist_id": checklist.id,
                    "state": "not_available",
                },
            )
            for checklist in self.kategori.default_checklist_ids
        ]

    # =========================================================
    # COMPUTE NILAI KONTRAK TERKINI
    # =========================================================

    @api.depends(
        "nilai_kontrak_awal",
        "addendum_ids.state",
        "addendum_ids.nilai_kontrak_baru",
        "addendum_ids.tanggal_perubahan",
    )
    def _compute_nilai_kontrak_terkini(self):
        for project in self:
            approved_addenda = project.addendum_ids.filtered(
                lambda addendum: addendum.state == "approved"
            )

            if approved_addenda:
                latest_addendum = approved_addenda.sorted(
                    key=lambda addendum: (
                        addendum.tanggal_perubahan
                        or fields.Date.today(),
                        addendum.id,
                    ),
                    reverse=True,
                )[0]

                project.nilai_kontrak_terkini = (
                    latest_addendum.nilai_kontrak_baru
                )
            else:
                project.nilai_kontrak_terkini = (
                    project.nilai_kontrak_awal
                )

    # =========================================================
    # COMPUTE SISA NILAI KONTRAK
    # =========================================================

    @api.depends(
        "nilai_kontrak_terkini",
        "term_ids.state",
        "term_ids.nominal",
    )
    def _compute_sisa_nilai_kontrak(self):
        for project in self:
            total_ditagih = sum(
                project.term_ids.filtered(
                    lambda term: term.state == "sudah_ditagih"
                ).mapped("nominal")
            )

            project.sisa_nilai_kontrak = (
                project.nilai_kontrak_terkini - total_ditagih
            )

    # =========================================================
    # GENERATE TERMIN
    # =========================================================

    def action_generate_terms(self):
        self.ensure_one()

        if not self.sistem_penagihan:
            raise ValidationError(
                "Sistem Penagihan harus dipilih terlebih dahulu."
            )

        # -----------------------------------------------------
        # CEGAH GENERATE ULANG
        # -----------------------------------------------------

        if self.term_ids:
            raise ValidationError(
                "Termin sudah tersedia pada proyek ini. "
                "Hapus termin yang ada terlebih dahulu jika ingin "
                "melakukan generate ulang."
            )

        # -----------------------------------------------------
        # VALIDASI TANGGAL KONTRAK
        # -----------------------------------------------------

        if not self.awal_kontrak or not self.akhir_kontrak:
            raise ValidationError(
                "Awal Kontrak dan Akhir Kontrak wajib diisi "
                "sebelum Generate Termin."
            )

        if self.akhir_kontrak < self.awal_kontrak:
            raise ValidationError(
                "Tanggal Akhir Kontrak tidak boleh lebih kecil "
                "dari Tanggal Awal Kontrak."
            )

        # -----------------------------------------------------
        # PER TERMIN
        # -----------------------------------------------------
        #
        # Per Termin diisi manual oleh user.
        #

        if self.sistem_penagihan == "per_termin":
            raise ValidationError(
                "Untuk sistem Per Termin, data termin diisi secara manual."
            )

        # -----------------------------------------------------
        # PELUNASAN 100%
        # -----------------------------------------------------

        if self.sistem_penagihan == "pelunasan_100":
            return self._generate_pelunasan_100()

        # -----------------------------------------------------
        # PER BULAN
        # -----------------------------------------------------

        if self.sistem_penagihan == "per_bulan":
            return self._generate_termin_berkala(
                month_interval=1
            )

        # -----------------------------------------------------
        # PER 3 BULAN
        # -----------------------------------------------------

        if self.sistem_penagihan == "per_3_bulan":
            return self._generate_termin_berkala(
                month_interval=3
            )

        raise ValidationError(
            "Sistem Penagihan tidak dikenali."
        )

    # =========================================================
    # GENERATE PELUNASAN 100%
    # =========================================================

    def _generate_pelunasan_100(self):
        self.ensure_one()

        self.env["ksg.sales.project.term"].create(
            {
                "project_id": self.id,
                "no_termin": 1,
                "deskripsi": "Pelunasan 100%",
                "persentase": 100.0,
                "tanggal_jatuh_tempo": self.akhir_kontrak,
            }
        )

        self.message_post(
            body=(
                "Termin Pelunasan 100% berhasil dibuat otomatis "
                f"untuk proyek {self.kode_proyek}."
            ),
            subtype_xmlid="mail.mt_note",
        )

        return True

    # =========================================================
    # GENERATE TERMIN BERKALA
    # =========================================================

    def _generate_termin_berkala(self, month_interval):
        self.ensure_one()

        from dateutil.relativedelta import relativedelta

        tanggal = self.awal_kontrak
        tanggal_akhir = self.akhir_kontrak

        tanggal_list = []

        # -----------------------------------------------------
        # BUAT DAFTAR TANGGAL TERMIN
        # -----------------------------------------------------

        while tanggal <= tanggal_akhir:
            tanggal_list.append(tanggal)

            tanggal = tanggal + relativedelta(
                months=month_interval
            )

        if not tanggal_list:
            raise ValidationError(
                "Tidak dapat membuat jadwal termin "
                "berdasarkan periode kontrak."
            )

        jumlah_termin = len(tanggal_list)

        # -----------------------------------------------------
        # BAGI PERSENTASE
        # -----------------------------------------------------

        persentase_dasar = round(
            100.0 / jumlah_termin,
            2,
        )

        terms = []

        total_persentase = 0.0

        # -----------------------------------------------------
        # BUAT TERMIN
        # -----------------------------------------------------

        for index, tanggal_jatuh_tempo in enumerate(
            tanggal_list,
            start=1,
        ):
            if index == jumlah_termin:
                persentase = round(
                    100.0 - total_persentase,
                    2,
                )
            else:
                persentase = persentase_dasar

            total_persentase += persentase

            # -------------------------------------------------
            # DESKRIPSI
            # -------------------------------------------------

            if month_interval == 1:
                deskripsi = f"Termin Bulan ke-{index}"
            else:
                deskripsi = f"Termin Periode ke-{index}"

            terms.append(
                {
                    "project_id": self.id,
                    "no_termin": index,
                    "deskripsi": deskripsi,
                    "persentase": persentase,
                    "tanggal_jatuh_tempo": tanggal_jatuh_tempo,
                }
            )

        # -----------------------------------------------------
        # CREATE SEMUA TERMIN
        # -----------------------------------------------------

        self.env["ksg.sales.project.term"].create(terms)

        # -----------------------------------------------------
        # LABEL SISTEM PENAGIHAN
        # -----------------------------------------------------

        if month_interval == 1:
            sistem_label = "Per Bulan"
        else:
            sistem_label = "Per 3 Bulan"

        # -----------------------------------------------------
        # CHATTER
        # -----------------------------------------------------

        self.message_post(
            body=(
                f"Generate Termin {sistem_label} berhasil. "
                f"{jumlah_termin} termin berhasil dibuat "
                f"dengan total persentase "
                f"{total_persentase:.2f}%."
            ),
            subtype_xmlid="mail.mt_note",
        )

        return True

    # =========================================================
    # VALIDASI TANGGAL KONTRAK
    # =========================================================

    @api.constrains(
        "awal_kontrak",
        "akhir_kontrak",
    )
    def _check_contract_dates(self):
        for project in self:
            if (
                project.awal_kontrak
                and project.akhir_kontrak
                and project.akhir_kontrak < project.awal_kontrak
            ):
                raise ValidationError(
                    "Tanggal Akhir Kontrak tidak boleh lebih kecil "
                    "dari Tanggal Awal Kontrak."
                )

    # =========================================================
    # VALIDASI NILAI KONTRAK
    # =========================================================

    @api.constrains("nilai_kontrak_awal")
    def _check_nilai_kontrak_awal(self):
        for project in self:
            if project.nilai_kontrak_awal < 0:
                raise ValidationError(
                    "Nilai Kontrak tidak boleh bernilai negatif."
                )

    # =========================================================
    # VALIDASI CHECKLIST
    # =========================================================

    @api.constrains("checklist_dokumen_ids")
    def _check_checklist_dokumen(self):
        for project in self:
            if not project.checklist_dokumen_ids:
                raise ValidationError(
                    "Checklist Dokumen Engineering wajib diisi."
                )