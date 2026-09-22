from odoo import api, models


class CustomPayrollSlip(models.Model):
    _inherit = 'custom.payroll.slip'

    def _company_wage_amount(self):
        """Wage for this slip's work location (company), with contract fallback."""
        self.ensure_one()
        if not self.employee_id:
            return 0.0
        return self.employee_id._get_company_wage(self.work_location_id)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        res = super()._onchange_employee_id()
        if self.employee_id:
            self.total_gaji_pokok = self._company_wage_amount()
        return res

    @api.onchange('work_location_id')
    def _onchange_work_location_id_company_wage(self):
        if self.employee_id and self.status == 'draft':
            self.total_gaji_pokok = self._company_wage_amount()

    def _auto_populate_basic_salary_and_bpjs(self, *args, **kwargs):
        # Keep the basic salary aligned with the per-company wage BEFORE the
        # basic salary / BPJS / salary rules are computed, so all downstream
        # amounts use the correct base. Covers both the generation wizard and
        # the "Split by Location" action.
        for slip in self:
            if slip.status == 'draft' and slip.employee_id and slip.work_location_id:
                slip.total_gaji_pokok = slip.employee_id._get_company_wage(
                    slip.work_location_id,
                )
        return super()._auto_populate_basic_salary_and_bpjs(*args, **kwargs)
