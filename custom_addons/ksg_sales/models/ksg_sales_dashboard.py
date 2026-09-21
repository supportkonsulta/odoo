from odoo import fields, models


class KsgSalesDashboard(models.Model):
    _name = "ksg.sales.dashboard"
    _description = "KSG Sales Dashboard"
    _rec_name = "name"

    name = fields.Char(
        string="Dashboard",
        default="Dashboard Penjualan KSG",
        required=True,
    )

    total_project = fields.Integer(
        string="Total Proyek",
        compute="_compute_dashboard",
    )

    total_contract = fields.Monetary(
        string="Total Nilai Kontrak",
        compute="_compute_dashboard",
    )

    total_remaining_contract = fields.Monetary(
        string="Sisa Nilai Kontrak",
        compute="_compute_dashboard",
    )

    project_active = fields.Integer(
        string="Proyek Aktif",
        compute="_compute_dashboard",
    )

    project_completed = fields.Integer(
        string="Proyek Selesai",
        compute="_compute_dashboard",
    )

    project_cancelled = fields.Integer(
        string="Proyek Batal",
        compute="_compute_dashboard",
    )

    term_unbilled = fields.Integer(
        string="Belum Ditagih",
        compute="_compute_dashboard",
    )

    term_due = fields.Integer(
        string="Jatuh Tempo",
        compute="_compute_dashboard",
    )

    term_billed = fields.Integer(
        string="Sudah Ditagih",
        compute="_compute_dashboard",
    )

    currency_id = fields.Many2one(
        "res.currency",
        string="Mata Uang",
        compute="_compute_dashboard",
    )

    def _compute_dashboard(self):
        Project = self.env["ksg.sales.project"]
        Term = self.env["ksg.sales.project.term"]

        projects = Project.search([])
        terms = Term.search([])
        company_currency = self.env.company.currency_id

        for dashboard in self:
            dashboard.currency_id = company_currency

            dashboard.total_project = len(projects)

            dashboard.total_contract = sum(
                projects.mapped("nilai_kontrak_terkini")
            )

            dashboard.total_remaining_contract = sum(
                projects.mapped("sisa_nilai_kontrak")
            )

            dashboard.project_active = len(
                projects.filtered(
                    lambda p: p.status == "aktif"
                )
            )

            dashboard.project_completed = len(
                projects.filtered(
                    lambda p: p.status == "selesai"
                )
            )

            dashboard.project_cancelled = len(
                projects.filtered(
                    lambda p: p.status == "batal"
                )
            )

            dashboard.term_unbilled = len(
                terms.filtered(
                    lambda t: t.state not in (
                        "sudah_ditagih",
                        "jatuh_tempo",
                    )
                )
            )

            dashboard.term_due = len(
                terms.filtered(
                    lambda t: t.state == "jatuh_tempo"
                )
            )

            dashboard.term_billed = len(
                terms.filtered(
                    lambda t: t.state == "sudah_ditagih"
                )
            )