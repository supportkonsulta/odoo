from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    slip_ids = fields.One2many('custom.payroll.slip', 'employee_id', string='Payslips')
    slip_count = fields.Integer(string='Payslip Count', compute='_compute_slip_count')

    def _compute_slip_count(self):
        for rec in self:
            rec.slip_count = len(rec.slip_ids)

    def action_view_slips(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payslips',
            'res_model': 'custom.payroll.slip',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def _get_version_for_location(self, work_location=None):
        """Return the ``hr.version`` matching ``(employee, work_location)``.

        Falls back to the employee's current version when no matching
        version exists, so payroll slips stay populated even if HR has not
        yet created a per-location version for a multi-company employee.
        """
        self.ensure_one()
        location = work_location or self.work_location_id
        if location:
            match = self.version_ids.filtered(
                lambda v: v.work_location_id == location,
            )[:1]
            if match:
                return match
        return self.version_id

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        for employee in employees:
            if employee.presenly_client_ids:
                employee._sync_contract_versions_from_branches()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if 'presenly_client_ids' in vals:
            for employee in self:
                employee._sync_contract_versions_from_branches()
        return result

    def _sync_contract_versions_from_branches(self):
        """Auto-create contract versions for each work location from branches.

        Creates one hr.version per active work location belonging to any
        branch in presenly_client_ids. Skips locations that already have
        a contract version for this employee.
        """
        self.ensure_one()
        HrVersion = self.env['hr.version']
        HrWorkLocation = self.env['hr.work.location']
        today = fields.Date.today()

        for company in self.presenly_client_ids:
            locations = HrWorkLocation.search([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ])

            for location in locations:
                existing = HrVersion.search([
                    ('employee_id', '=', self.id),
                    ('work_location_id', '=', location.id),
                ], limit=1)

                if not existing:
                    HrVersion.create({
                        'employee_id': self.id,
                        'work_location_id': location.id,
                        'date_version': today,
                        'wage': 0.0,
                    })
