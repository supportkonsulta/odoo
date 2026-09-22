from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrEmployeeCompanyWage(models.Model):
    """Fixed wage for one employee at one company.

    Presenly represents each paying company as an ``hr.work.location`` inside a
    single ``res.company``. Odoo keeps a single wage per employee
    (``hr.version.contract_wage``), which cannot express "a different fixed wage
    per company" for one person. This model fills that gap: one fixed nominal
    per (employee, work location = company).
    """

    _name = 'hr.employee.company.wage'
    _description = 'Employee Wage per Company'
    _order = 'employee_id, work_location_id'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        ondelete='cascade', index=True,
    )
    work_location_id = fields.Many2one(
        'hr.work.location', string='Company / Work Location', required=True,
        ondelete='cascade', index=True, check_company=True,
        help='Company (work location) this wage applies to.',
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        related='work_location_id.company_id', store=True, readonly=True, index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True,
    )
    wage = fields.Monetary(
        string='Wage', required=True, default=0.0, currency_field='currency_id',
        help='Fixed monthly basic salary for this employee at this company.',
    )
    valid_from = fields.Date(string='Valid From')
    valid_to = fields.Date(string='Valid To')
    active = fields.Boolean(default=True)

    _company_wage_uniq = models.UniqueIndex(
        '(employee_id, work_location_id)',
        'A wage already exists for this employee at this work location.',
    )
    _company_wage_non_negative = models.Constraint(
        'CHECK(wage >= 0)',
        'Wage must not be negative.',
    )

    @api.constrains('valid_from', 'valid_to')
    def _check_valid_dates(self):
        for rec in self:
            if rec.valid_from and rec.valid_to and rec.valid_from > rec.valid_to:
                raise ValidationError(_('Valid To must be after Valid From.'))
