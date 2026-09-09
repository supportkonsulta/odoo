from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase
from odoo.tests import new_test_user


class TestPresenlySetupGuide(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Use a fresh company so counts are deterministic.
        cls.company = cls.env['res.company'].create({
            'name': 'Setup Guide Test Co',
        })
        cls.manager_user = new_test_user(
            cls.env,
            login='setup_manager',
            groups='base.group_user,presenly.group_presenly_manager',
        )
        cls.manager_user.company_ids = [(4, cls.company.id)]
        cls.employee_user = new_test_user(
            cls.env,
            login='setup_employee',
            groups='base.group_user,presenly.group_presenly_employee',
        )

    def _guide(self, user=None):
        guide = self.env['presenly.setup.guide'].with_user(
            user or self.env.user
        ).create({'company_id': self.company.id})
        return guide

    def test_guide_computes_counts_for_company(self):
        address = self.env['res.partner'].create({
            'name': 'Setup Guide Location',
            'company_id': self.company.id,
            'partner_latitude': -6.2,
            'partner_longitude': 106.8,
        })
        self.env['hr.work.location'].create({
            'name': 'Setup Guide Location',
            'company_id': self.company.id,
            'address_id': address.id,
        })
        guide = self._guide()
        self.assertEqual(guide.location_total, 1)
        self.assertGreaterEqual(guide.location_ready, 0)
        self.assertEqual(guide.step_total, 8)
        self.assertTrue(0 <= guide.progress <= 100)

    def test_guide_menu_and_action_manager_only(self):
        menu = self.env.ref('presenly.menu_presenly_setup_guide')
        self.assertTrue(menu.active)
        action = self.env.ref('presenly.action_presenly_setup_guide')
        self.assertEqual(menu.action.id, action.id)
        self.assertIn(
            self.env.ref('presenly.group_presenly_manager'), menu.group_ids,
        )
        # Non-manager cannot access the guide model via the menu action.
        try:
            self.env['presenly.setup.guide'].with_user(
                self.employee_user
            ).check_access('read')
            raise AssertionError('Employee should not read the setup guide')
        except AccessError:
            pass

    def test_guide_shortcut_actions_resolve(self):
        guide = self._guide(user=self.manager_user)
        for method in (
            'action_open_companies',
            'action_open_locations',
            'action_open_schedules',
            'action_open_employees',
            'action_open_permission_types',
            'action_open_leave_types',
            'action_open_approval_routes',
            'action_generate_approval_routes',
        ):
            action = getattr(guide, method)()
            self.assertIn(action['type'], ('ir.actions.act_window', 'ir.actions.act_window_close'))
            self.assertTrue(action['res_model'])


class TestPresenlyApprovalRouteGenerate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A clean company isolates generation tests from production data
        # (company 1 already has overtime/leave routes in the clone).
        cls.company = cls.env['res.company'].create({
            'name': 'Route Generation Test Co',
        })
        cls.permission_type = cls.env['presenly.permission.type'].create({
            'name': 'Gen Permission',
            'code': 'GEN_PERM',
            'company_id': cls.company.id,
            'request_mode': 'full_day',
            'paid_status': 'policy',
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Gen Leave',
            'company_id': cls.company.id,
            'requires_allocation': False,
            'leave_validation_type': 'manager',
        })
        cls.manager_user = new_test_user(
            cls.env,
            login='gen_manager',
            groups='base.group_user,presenly.group_presenly_manager',
        )
        cls.manager_user.company_ids = [(4, cls.company.id)]

    def _wizard(self, **overrides):
        values = {
            'company_id': self.company.id,
            'apply_to': overrides.pop('apply_to', 'all'),
            'approver_type': 'employee_manager',
            'skip_existing': True,
        }
        values.update(overrides)
        return self.env['presenly.approval.route.generate.wizard'].create(
            values
        )

    def test_generate_overtime_route(self):
        wizard = self._wizard(apply_to='overtime')
        wizard._prepare_lines()
        to_create = wizard.line_ids.filtered(
            lambda line: line.status == 'to_create'
        )
        self.assertEqual(len(to_create), 1)
        wizard.with_user(self.manager_user).action_generate()
        rule = self.env['presenly.approval.rule'].search([
            ('company_id', '=', self.company.id),
            ('is_overtime_route', '=', True),
        ])
        self.assertTrue(rule)
        self.assertTrue(rule.is_complete)
        self.assertTrue(rule.active)
        self.assertEqual(rule.sequence, 10)
        # Idempotent: running again with skip_existing creates nothing.
        wizard2 = self._wizard(apply_to='overtime')
        wizard2._prepare_lines()
        self.assertTrue(all(
            line.status == 'skipped' for line in wizard2.line_ids
        ))

    def test_generate_leave_routes_sequence(self):
        wizard = self._wizard(
            apply_to='leave',
            leave_type_ids=[(6, 0, [self.leave_type.id])],
        )
        wizard._prepare_lines()
        to_create = wizard.line_ids.filtered(
            lambda line: line.status == 'to_create'
        )
        self.assertTrue(to_create)
        wizard.action_generate()
        rules = self.env['presenly.approval.rule'].search([
            ('company_id', '=', self.company.id),
            ('leave_type_id', '=', self.leave_type.id),
        ])
        self.assertTrue(rules)
        self.assertEqual(rules[0].sequence, 10)

    def test_skip_existing_false_creates_second_step(self):
        wizard = self._wizard(apply_to='permission')
        wizard.action_generate()
        self.assertEqual(
            self.env['presenly.approval.rule'].search_count([
                ('company_id', '=', self.company.id),
                ('permission_type_id', '=', self.permission_type.id),
            ]),
            1,
        )
        # Disable skip: a second step is appended (auto Order is 20).
        wizard2 = self._wizard(apply_to='permission', skip_existing=False)
        wizard2.action_generate()
        rules = self.env['presenly.approval.rule'].search([
            ('company_id', '=', self.company.id),
            ('permission_type_id', '=', self.permission_type.id),
        ], order='sequence')
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].sequence, 10)
        self.assertEqual(rules[1].sequence, 20)

    def test_all_mode_filters_to_selected_types(self):
        """In 'all' mode the preview and generation must reflect the selected
        types immediately: picking 2 leave + 1 permission type must NOT list
        every other active leave type."""
        # Second leave type, unrelated to the first one.
        other_leave = self.env['hr.leave.type'].create({
            'name': 'Gen Leave Unrelated',
            'company_id': self.company.id,
            'requires_allocation': False,
            'leave_validation_type': 'manager',
        })
        wizard = self._wizard(
            apply_to='all',
            leave_type_ids=[(6, 0, [self.leave_type.id, other_leave.id])],
            permission_type_ids=[(6, 0, [self.permission_type.id])],
        )
        wizard._prepare_lines()
        lines = wizard.line_ids
        self.assertEqual(len(lines), 4)  # 2 leave + 1 permission + 1 overtime
        names = lines.mapped('request_name')
        self.assertIn('Gen Leave', names)
        self.assertIn('Gen Leave Unrelated', names)
        self.assertIn('Gen Permission', names)
        self.assertIn('Overtime (all employees)', names)
        self.assertEqual(
            len(lines.filtered(lambda line: line.status == 'to_create')), 4,
        )
        # No unrelated leave type leaked into the preview.
        self.assertNotIn('Paid Time Off', names)
        self.assertNotIn('Sick Time Off', names)

    def test_generate_wizard_menu_manager_only(self):
        menu = self.env.ref(
            'presenly.menu_presenly_approval_route_generate'
        )
        self.assertTrue(menu.active)
        self.assertIn(
            self.env.ref('presenly.group_presenly_manager'), menu.group_ids,
        )
        try:
            self.env['presenly.approval.route.generate.wizard'].with_user(
                new_test_user(
                    self.env,
                    login='gen_employee',
                    groups='base.group_user,presenly.group_presenly_employee',
                )
            ).check_access('read')
            raise AssertionError('Employee should not read the wizard')
        except AccessError:
            pass