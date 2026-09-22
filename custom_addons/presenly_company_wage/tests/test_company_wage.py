from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestCompanyWage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Wage = cls.env['hr.employee.company.wage']
        cls.Slip = cls.env['custom.payroll.slip']

        cls.address_a = cls.env['res.partner'].create({
            'name': 'Company A',
            'company_id': cls.company.id,
        })
        cls.address_b = cls.env['res.partner'].create({
            'name': 'Company B',
            'company_id': cls.company.id,
        })
        cls.location_a = cls.env['hr.work.location'].create({
            'name': 'Company A Site',
            'company_id': cls.company.id,
            'address_id': cls.address_a.id,
        })
        cls.location_b = cls.env['hr.work.location'].create({
            'name': 'Company B Site',
            'company_id': cls.company.id,
            'address_id': cls.address_b.id,
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Multi Company Employee',
            'company_id': cls.company.id,
            'work_location_id': cls.location_a.id,
        })
        cls.employee.write({'wage': 4000000.0})

        cls.batch = cls.env['custom.payroll.batch'].create({
            'name': 'Company Wage Batch',
            'periode_bulan': '8',
            'periode_tahun': 2030,
            'company_id': cls.company.id,
        })

    def test_wage_per_location_is_returned(self):
        self.Wage.create({
            'employee_id': self.employee.id,
            'work_location_id': self.location_a.id,
            'wage': 5000000.0,
        })
        self.Wage.create({
            'employee_id': self.employee.id,
            'work_location_id': self.location_b.id,
            'wage': 3250000.0,
        })
        self.assertEqual(
            self.employee._get_company_wage(self.location_a), 5000000.0,
        )
        self.assertEqual(
            self.employee._get_company_wage(self.location_b), 3250000.0,
        )

    def test_fallback_to_contract_wage(self):
        # No mapping for location B -> contract wage (4,000,000) is used.
        self.assertEqual(
            self.employee._get_company_wage(self.location_b), 4000000.0,
        )

    def test_unique_wage_per_employee_location(self):
        self.Wage.create({
            'employee_id': self.employee.id,
            'work_location_id': self.location_a.id,
            'wage': 5000000.0,
        })
        with self.assertRaises(Exception):
            self.Wage.create({
                'employee_id': self.employee.id,
                'work_location_id': self.location_a.id,
                'wage': 111.0,
            })

    def test_negative_wage_rejected(self):
        with self.assertRaises(Exception):
            self.Wage.create({
                'employee_id': self.employee.id,
                'work_location_id': self.location_a.id,
                'wage': -1.0,
            })

    def test_invalid_validity_dates_rejected(self):
        with self.assertRaises(ValidationError):
            self.Wage.create({
                'employee_id': self.employee.id,
                'work_location_id': self.location_a.id,
                'wage': 1000.0,
                'valid_from': '2030-02-01',
                'valid_to': '2030-01-01',
            })

    def test_slip_basic_salary_uses_location_wage(self):
        self.Wage.create({
            'employee_id': self.employee.id,
            'work_location_id': self.location_a.id,
            'wage': 5000000.0,
        })
        self.Wage.create({
            'employee_id': self.employee.id,
            'work_location_id': self.location_b.id,
            'wage': 3250000.0,
        })

        slip_a = self.Slip.create({
            'payroll_batch_id': self.batch.id,
            'employee_id': self.employee.id,
            'work_location_id': self.location_a.id,
            'company_id': self.company.id,
        })
        slip_a._auto_populate_basic_salary_and_bpjs()
        self.assertEqual(slip_a.total_gaji_pokok, 5000000.0)

        slip_b = self.Slip.create({
            'payroll_batch_id': self.batch.id,
            'employee_id': self.employee.id,
            'work_location_id': self.location_b.id,
            'company_id': self.company.id,
        })
        slip_b._auto_populate_basic_salary_and_bpjs()
        self.assertEqual(slip_b.total_gaji_pokok, 3250000.0)

    def test_slip_basic_salary_falls_back_to_contract(self):
        slip = self.Slip.create({
            'payroll_batch_id': self.batch.id,
            'employee_id': self.employee.id,
            'work_location_id': self.location_b.id,
            'company_id': self.company.id,
        })
        slip._auto_populate_basic_salary_and_bpjs()
        self.assertEqual(slip.total_gaji_pokok, 4000000.0)
