from odoo import api, models


class CustomPayrollGenerateWizard(models.TransientModel):
    _inherit = 'custom.payroll.generate.wizard'

    @api.model
    def _company_wage_for_line(self, employee_id, work_location_id):
        employee = self.env['hr.employee'].browse(employee_id).exists()
        location = self.env['hr.work.location'].browse(work_location_id).exists()
        if employee and location:
            return employee._get_company_wage(location)
        return None

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        lines = vals.get('preview_line_ids')
        if lines:
            for command in lines:
                data = command[2] if len(command) > 2 else {}
                wage = self._company_wage_for_line(
                    data.get('employee_id'), data.get('work_location_id'),
                )
                if wage is not None:
                    data['contract_wage'] = wage
        return vals

    def _refresh_preview(self):
        res = super()._refresh_preview()
        for line in self.preview_line_ids:
            wage = self._company_wage_for_line(
                line.employee_id.id, line.work_location_id.id,
            )
            if wage is not None:
                line.contract_wage = wage
        return res
