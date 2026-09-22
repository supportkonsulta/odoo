from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    company_wage_ids = fields.One2many(
        'hr.employee.company.wage', 'employee_id',
        string='Wages per Company',
    )

    def _get_company_wage(self, work_location=None, on_date=None):
        """Return the fixed wage configured for ``work_location`` (company).

        Falls back to the employee's contract wage
        (``hr.version.contract_wage``) when no per-company wage is configured,
        so behaviour is unchanged for employees without a mapping.
        """
        self.ensure_one()
        location = work_location or self.work_location_id
        if location:
            domain = [
                ('employee_id', '=', self.id),
                ('work_location_id', '=', location.id),
            ]
            if on_date:
                domain += ['|', ('valid_from', '=', False), ('valid_from', '<=', on_date)]
                domain += ['|', ('valid_to', '=', False), ('valid_to', '>=', on_date)]
            mapping = self.env['hr.employee.company.wage'].search(
                domain, order='valid_from desc, id desc', limit=1,
            )
            if mapping:
                return mapping.wage
        if self.version_id:
            return self.version_id.contract_wage
        return 0.0
