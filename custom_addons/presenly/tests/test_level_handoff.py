from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPresenlyLevelHandoff(TransactionCase):
    """After level 1 approves, the level-1 approver must NOT be able to
    approve again, must NOT see the request in their approval queue, and the
    request must move to the level-2 approvers only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Deliberately NO Presenly Approver role and NO Time Off officer group:
        # approval rights must come dynamically from the Approval Route
        # assignment alone (the global pending-only record rule grants access).
        cls.employee_user = cls.env['res.users'].create({
            'name': 'Handoff Employee',
            'login': 'handoff_employee',
            'email': 'handoff.employee@example.com',
            'group_ids': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.level1_user = cls.env['res.users'].create({
            'name': 'Level One Approver',
            'login': 'handoff_level1',
            'email': 'handoff.level1@example.com',
            'group_ids': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.level2_user = cls.env['res.users'].create({
            'name': 'Level Two Approver',
            'login': 'handoff_level2',
            'email': 'handoff.level2@example.com',
            'group_ids': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.location_address = cls.env['res.partner'].create({
            'name': 'Handoff Address',
            'company_id': cls.company.id,
        })
        cls.location = cls.env['hr.work.location'].create({
            'name': 'Handoff Location',
            'company_id': cls.company.id,
            'address_id': cls.location_address.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Handoff Employee',
            'company_id': cls.company.id,
            'user_id': cls.employee_user.id,
            'work_location_id': cls.location.id,
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Handoff Leave',
            'company_id': cls.company.id,
            'requires_allocation': False,
            'leave_validation_type': 'manager',
        })
        cls.env['presenly.approval.rule'].create({
            'name': 'Level One Step',
            'company_id': cls.company.id,
            'leave_type_id': cls.leave_type.id,
            'sequence': 10,
            'approver_type': 'user',
            'approver_user_id': cls.level1_user.id,
        })
        cls.env['presenly.approval.rule'].create({
            'name': 'Level Two Step',
            'company_id': cls.company.id,
            'leave_type_id': cls.leave_type.id,
            'sequence': 20,
            'approver_type': 'user',
            'approver_user_id': cls.level2_user.id,
        })

    def _create_and_submit_leave(self):
        # Monday 2030-03-11: a working day for the default calendar.
        leave = self.env['hr.leave'].with_user(self.employee_user).create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type.id,
            'presenly_work_location_id': self.location.id,
            'request_date_from': '2030-03-11',
            'request_date_to': '2030-03-11',
            'name': 'Handoff test leave',
        })
        leave.action_presenly_submit()
        return leave

    def test_level1_cannot_approve_after_handoff(self):
        leave = self._create_and_submit_leave()
        approval = leave.presenly_approval_request_id
        self.assertEqual(approval.current_step_id.level, 1)
        # Level 1 approves -> moves to level 2.
        leave.with_user(self.level1_user).action_presenly_approve()
        self.assertEqual(approval.current_step_id.level, 2)
        self.assertEqual(approval.step_ids[0].state, 'approved')
        self.assertEqual(approval.step_ids[1].state, 'pending')
        # UI flag for level-1 user must be False now.
        leaf = leave.with_user(self.level1_user)
        self.assertFalse(leaf.presenly_can_approve)
        self.assertFalse(leaf.presenly_can_reject)
        # Server guard must reject a second approval from level 1.
        with self.assertRaises(UserError):
            leave.with_user(self.level1_user).action_presenly_approve()

    def test_level1_not_in_queue_after_handoff(self):
        leave = self._create_and_submit_leave()
        leave.with_user(self.level1_user).action_presenly_approve()
        # Queue (web action) must no longer contain the leave for level 1.
        action = self.env['hr.leave'].with_user(
            self.level1_user
        ).action_open_presenly_approval_queue()
        self.assertNotIn(leave.id, action['domain'][0][2])
        # Level 2 sees it in the queue.
        action2 = self.env['hr.leave'].with_user(
            self.level2_user
        ).action_open_presenly_approval_queue()
        self.assertIn(leave.id, action2['domain'][0][2])

    def test_level2_can_approve_and_complete(self):
        leave = self._create_and_submit_leave()
        leave.with_user(self.level1_user).action_presenly_approve()
        leave.with_user(self.level2_user).action_presenly_approve()
        self.assertEqual(leave.presenly_approval_state, 'approved')
        self.assertEqual(leave.state, 'validate')

    def test_approver_rule_is_pending_only_and_global(self):
        """The presenly record rules must (a) only grant access to CURRENT
        pending approvers (never handled history) and (b) apply to every user
        (no group) so approval rights come from the route assignment alone."""
        rules = self.env['ir.rule'].search([
            ('model_id.model', 'in', [
                'hr.leave', 'presenly.permission', 'presenly.overtime.request',
            ]),
            ('name', 'like', 'Presenly approver%'),
        ])
        self.assertEqual(len(rules), 3)
        for rule in rules:
            self.assertNotIn(
                'presenly_approver_history_ids', rule.domain_force,
            )
            self.assertIn(
                'presenly_pending_approver_ids', rule.domain_force,
            )
            # Applies to every internal user (dynamic route-based access):
            # base.group_user must be among the rule groups (the legacy
            # Approver group may still be listed from previous installs but
            # it no longer gates anything).
            self.assertIn(
                self.env.ref('base.group_user'),
                rule.groups,
                f'{rule.name} must apply to base.group_user',
            )

    def test_approvers_without_role_can_approve(self):
        """Users assigned through Approval Routes approve without holding the
        (now legacy) Presenly Approver role."""
        leave = self._create_and_submit_leave()
        # Neither level1 nor level2 has presenly.group_presenly_approver.
        approval = leave.presenly_approval_request_id
        self.assertEqual(approval.current_step_id.level, 1)
        leave.with_user(self.level1_user).action_presenly_approve()
        leave.with_user(self.level2_user).action_presenly_approve()
        self.assertEqual(leave.presenly_approval_state, 'approved')