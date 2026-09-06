from odoo import fields, models


class CustomPayrollRule(models.Model):
    _name = 'custom.payroll.rule'
    _description = 'Flexible Salary Rule'
    _order = 'sequence, id'

    name = fields.Char(string='Rule Name', required=True, translate=True)
    code = fields.Char(
        string='Code',
        required=True,
        help='Unique short code. Used as identifier and in descriptions.',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    category_id = fields.Many2one(
        'custom.payroll.rule.category',
        string='Category',
        required=True,
    )
    condition = fields.Text(
        string='Condition (Python)',
        default='True',
        help='Python expression that returns True/False. '
             'Available variables: employee, contract, payslip, categories, result. '
             'Example: payslip.payroll_batch_id.periode_bulan == "12"',
    )
    amount_python = fields.Text(
        string='Amount Computation (Python)',
        required=True,
        help='Python code that sets the "result" variable. '
             'Available variables: employee, contract, payslip, categories, result. '
             'Examples:\n'
             '  result = categories.BASIC * 0.05\n'
             '  result = contract.wage * 0.5\n'
             '  result = 500000 if employee.children > 2 else 0',
    )
    appears_on_payslip = fields.Boolean(
        string='Appears on Payslip',
        default=True,
        help='If checked, this rule will generate a line on the payslip.',
    )
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'Code must be unique per company!',
    )
