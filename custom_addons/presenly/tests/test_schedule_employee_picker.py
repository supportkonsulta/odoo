from odoo.exceptions import ValidationError
from odoo.tests.common import Form, TransactionCase


class TestPresenlyScheduleEmployeePicker(TransactionCase):
    """Work Location Schedule employee picker must list employees even when
    the schedule is still new (company_id not set yet)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.address = cls.env['res.partner'].create({
            'name': 'Picker Office Address',
            'company_id': cls.company.id,
        })
        cls.location = cls.env['hr.work.location'].create({
            'name': 'Picker Office',
            'company_id': cls.company.id,
            'address_id': cls.address.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Picker Employee',
            'company_id': cls.company.id,
            'work_location_id': cls.location.id,
        })
        cls.other_company = cls.env['res.company'].create({
            'name': 'Picker Other Co',
        })

    def test_employee_field_no_longer_restricts_new_record(self):
        field = self.env['presenly.work.location.schedule']._fields['employee_id']
        # Root cause: check_company=True generated a dropdown domain limited
        # to employees of the (still empty) record company -> empty picker.
        self.assertFalse(
            field.check_company,
            'employee_id must not use check_company so the picker lists '
            'employees on a brand-new schedule',
        )

    def test_new_schedule_can_pick_employee_and_location(self):
        """Browser-like flow: a brand-new schedule (no company yet) lets the
        user pick an employee even though record company is empty."""
        form = Form(
            self.env['presenly.work.location.schedule'],
            view='presenly.view_presenly_work_location_schedule_form',
        )
        form.employee_id = self.employee
        form.work_location_id = self.location
        form.hour_from = 8.0
        form.hour_to = 12.0
        schedule = form.save()
        self.assertEqual(schedule.company_id, self.company)
        self.assertEqual(schedule.employee_id, self.employee)
        self.assertEqual(schedule.work_location_id, self.location)

    def test_company_consistency_guard_still_enforced(self):
        """Removing check_company must not weaken the company rule: employee
        and work location of different companies are still rejected."""
        other_location = self.env['hr.work.location'].create({
            'name': 'Other Co Office',
            'company_id': self.other_company.id,
            'address_id': self.env['res.partner'].create({
                'name': 'Other Co Address',
                'company_id': self.other_company.id,
            }).id,
        })
        with self.assertRaises(ValidationError):
            self.env['presenly.work.location.schedule'].create({
                'employee_id': self.employee.id,
                'work_location_id': other_location.id,
                'hour_from': 8.0,
                'hour_to': 12.0,
            })