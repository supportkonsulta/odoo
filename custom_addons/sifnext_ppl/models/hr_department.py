from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrDepartment(models.Model):
    _inherit = "hr.department"

    code = fields.Char(
        string="Kode Unit",
        index=True,
        help="Kode singkat untuk penomoran dokumen (contoh: SD, SMP, YP).",
    )
    journal_unit_dept = fields.Selection(
        [("tpa", "TPA"), ("sd", "SD"), ("smp", "SMP"), ("sma", "SMA"),
         ("univ", "Universitas"), ("pusat", "Yayasan / Kantor Pusat")],
        string="Unit Jurnal",
        default="pusat",
        help="Mapping department ke kolom Unit/Departemen pada Jurnal Besar.",
    )

    _code_company_uniq = models.Constraint(
        "unique (code, company_id)",
        "Kode Unit harus unik dalam satu perusahaan.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code"):
                vals["code"] = vals["code"].strip().upper()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("code"):
            vals["code"] = vals["code"].strip().upper()
        return super().write(vals)

    @api.constrains("code")
    def _check_code(self):
        for dept in self:
            if dept.code and not dept.code.replace("-", "").isalnum():
                raise ValidationError(_("Kode Unit hanya boleh berisi huruf, angka, dan tanda hubung."))


class ResUsers(models.Model):
    _inherit = "res.users"

    unit_id = fields.Many2one(
        "hr.department",
        string="Unit",
        domain="[('company_id', 'in', company_ids)]",
    )
