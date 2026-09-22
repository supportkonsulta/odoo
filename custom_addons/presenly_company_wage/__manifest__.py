{
    'name': 'Presenly Company Wage',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Fixed wage per company (work location) for employees working in several companies',
    'description': """
Presenly Company Wage
=====================
Odoo stores a single wage per employee (``hr.version``). When one employee
works for several companies, each company (represented in Presenly as a
``hr.work.location``) must be able to pay its own fixed wage.

This module adds a per-company wage table:

- ``hr.employee.company.wage``: one fixed nominal per (employee, work location).
- ``hr.employee`` gets ``_get_company_wage(work_location)`` with fallback to the
  contract wage, so existing behaviour is preserved when no mapping exists.
- ``custom.payroll.slip`` derives ``total_gaji_pokok`` from the wage of the
  slip's work location. Combined with the existing one-slip-per-location
  feature, a multi-company employee gets one payslip per company with the
  correct fixed wage.
- The "Generate Payslips" wizard preview shows the per-location wage.
    """,
    'author': 'Presenly',
    'website': '',
    'depends': [
        'hr_payroll_custom',
    ],
    'data': [
        'security/company_wage_security.xml',
        'security/ir.model.access.csv',
        'views/hr_employee_company_wage_views.xml',
        'views/hr_employee_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
