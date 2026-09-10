from odoo.tests.common import Form, TransactionCase


class TestPresenlyWizardScopeUx(TransactionCase):
    """Browser-like flow: simulate the exact onchange chain the UI sends when
    the user picks Time Off types / switches Apply To, and assert the preview
    lines match what the screen shows."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Wizard UX Co',
        })
        # Two leave types without routes, one routed leave type (simulates
        # Sick Time Off after the batch generation).
        cls.leave_new_1 = cls.env['hr.leave.type'].create({
            'name': 'UX Leave One',
            'company_id': cls.company.id,
            'requires_allocation': False,
            'leave_validation_type': 'manager',
        })
        cls.leave_new_2 = cls.env['hr.leave.type'].create({
            'name': 'UX Leave Two',
            'company_id': cls.company.id,
            'requires_allocation': False,
            'leave_validation_type': 'manager',
        })
        cls.leave_routed = cls.env['hr.leave.type'].create({
            'name': 'UX Leave Routed',
            'company_id': cls.company.id,
            'requires_allocation': False,
            'leave_validation_type': 'manager',
        })
        cls.permission_1 = cls.env['presenly.permission.type'].create({
            'name': 'UX Permission One',
            'code': 'UX_PERM_1',
            'company_id': cls.company.id,
            'request_mode': 'full_day',
            'paid_status': 'policy',
        })
        cls.permission_2 = cls.env['presenly.permission.type'].create({
            'name': 'UX Permission Two',
            'code': 'UX_PERM_2',
            'company_id': cls.company.id,
            'request_mode': 'full_day',
            'paid_status': 'policy',
        })
        cls.env['presenly.approval.rule'].create({
            'name': 'UX Leave Routed Step',
            'company_id': cls.company.id,
            'leave_type_id': cls.leave_routed.id,
            'approver_type': 'employee_manager',
        })

    def _open_wizard(self):
        return Form(
            self.env['presenly.approval.route.generate.wizard'],
            view='presenly.view_presenly_approval_route_generate_wizard_form',
        )

    def test_pick_leave_types_in_all_mode_only_shows_them(self):
        form = self._open_wizard()
        form.company_id = self.company
        form.apply_to = 'all'
        form.leave_type_ids.add(self.leave_new_1)
        form.leave_type_ids.add(self.leave_new_2)
        # Strict mode: picking types under 'all' limits the scope to the
        # picked types only — no permission lines, and NO overtime row either.
        wizard = form.save()
        lines = wizard.line_ids
        self.assertEqual(len(lines), 2)  # exactly the 2 picked leave types
        names = lines.mapped('request_name')
        self.assertIn('UX Leave One', names)
        self.assertIn('UX Leave Two', names)
        self.assertEqual(len(lines.filtered(
            lambda line: line.request_kind == 'leave'
        )), 2)
        self.assertEqual(len(lines.filtered(
            lambda line: line.request_kind == 'overtime'
        )), 0, 'Overtime must not be generated when types are picked')
        self.assertEqual(len(lines.filtered(
            lambda line: line.request_kind == 'permission'
        )), 0, 'No permission lines in strict leave scope')
        self.assertTrue(all(
            line.request_kind == 'leave' for line in lines
        ))
        self.assertEqual(
            len(lines.filtered(lambda line: line.status == 'to_create')), 2,
        )

    def test_apply_to_leave_never_shows_permission_lines(self):
        form = self._open_wizard()
        form.company_id = self.company
        form.apply_to = 'leave'
        form.leave_type_ids.add(self.leave_new_1)
        wizard = form.save()
        lines = wizard.line_ids
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.request_kind, 'leave')
        # A routed leave type is shown but flagged as skipped.
        form2 = self._open_wizard()
        form2.company_id = self.company
        form2.apply_to = 'leave'
        form2.leave_type_ids.add(self.leave_routed)
        wizard2 = form2.save()
        self.assertEqual(len(wizard2.line_ids), 1)
        self.assertEqual(wizard2.line_ids.status, 'skipped')
        self.assertEqual(wizard2.to_create_count, 0)
        self.assertEqual(wizard2.skipped_count, 1)

    def test_uncheck_skip_existing_offers_second_step_for_routed_type(self):
        form = self._open_wizard()
        form.company_id = self.company
        form.apply_to = 'leave'
        form.leave_type_ids.add(self.leave_routed)
        form.skip_existing = False
        wizard = form.save()
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.line_ids.status, 'to_create')
        # Preview shows the next free Order (existing step is 10).
        self.assertEqual(wizard.line_ids.sequence, 20)

    def test_apply_to_permission_shows_selected_permissions_only(self):
        form = self._open_wizard()
        form.company_id = self.company
        form.apply_to = 'permission'
        form.permission_type_ids.add(self.permission_1)
        wizard = form.save()
        lines = wizard.line_ids
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.request_kind, 'permission')
        self.assertIn('UX Permission One', lines.request_name)
        self.assertNotIn('UX Permission Two', lines.request_name)

    def test_all_mode_with_permission_selection_strict_leave_empty(self):
        form = self._open_wizard()
        form.company_id = self.company
        form.apply_to = 'all'
        form.permission_type_ids.add(self.permission_1)
        wizard = form.save()
        lines = wizard.line_ids
        # Strict all: only the selected permission — no leave, no overtime.
        self.assertEqual(len(lines), 1)
        self.assertIn('UX Permission One', lines.mapped('request_name'))
        self.assertNotIn('Overtime (all employees)', lines.mapped('request_name'))
        self.assertTrue(all(
            line.request_kind == 'permission' for line in lines
        ))