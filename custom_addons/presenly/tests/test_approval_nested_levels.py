from lxml import etree

from odoo.tests.common import Form, TransactionCase


class TestPresenlyApprovalNestedLevels(TransactionCase):
    """Nested Approval Routes UI (Company > Request Group > Request Type >
    Work Location > ordered levels) and the Add Next Level shortcut that
    reuses the same scope with the automatic next Order."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.permission_type = cls.env['presenly.permission.type'].create({
            'name': 'Nested Permission',
            'code': 'NESTED_PERM',
            'company_id': cls.company.id,
            'request_mode': 'full_day',
            'paid_status': 'policy',
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Nested Leave',
            'company_id': cls.company.id,
            'requires_allocation': False,
            'leave_validation_type': 'manager',
        })
        cls.leave_rule = cls.env['presenly.approval.rule'].create({
            'name': 'Level One',
            'company_id': cls.company.id,
            'leave_type_id': cls.leave_type.id,
            'approver_type': 'employee_manager',
        })

    def test_route_scope_label_computed(self):
        overtime = self.env['presenly.approval.rule'].create({
            'name': 'Overtime Step',
            'company_id': self.company.id,
            'is_overtime_route': True,
            'approver_type': 'employee_manager',
        })
        permission = self.env['presenly.approval.rule'].create({
            'name': 'Permission Step',
            'company_id': self.company.id,
            'permission_type_id': self.permission_type.id,
            'approver_type': 'employee_manager',
        })
        unassigned = self.env['presenly.approval.rule'].create({
            'name': 'Broken Step',
            'company_id': self.company.id,
            'approver_type': 'employee_manager',
        })
        self.assertEqual(self.leave_rule.route_scope_label, 'Time Off: Nested Leave')
        self.assertEqual(
            permission.route_scope_label, 'Permission: Nested Permission',
        )
        self.assertEqual(overtime.route_scope_label, 'Overtime')
        self.assertEqual(unassigned.route_scope_label, 'Unassigned')

    def test_list_view_nested_grouping(self):
        result = self.env['presenly.approval.rule'].get_view(
            view_id=self.env.ref('presenly.view_presenly_approval_rule_list').id,
            view_type='list',
        )
        root = etree.fromstring(result['arch'].encode())
        list_node = root.xpath('//list')[0]
        self.assertEqual(
            list_node.get('default_group_by'),
            'company_id,request_group,route_scope_label,work_location_id',
        )
        self.assertEqual(list_node.get('default_order'), 'sequence, id')
        self.assertEqual(list_node.get('create'), '0')
        self.assertEqual(list_node.get('edit'), '0')
        # Add Next Level button present on rows.
        self.assertEqual(
            len(root.xpath(
                "//button[@name='action_add_next_level']"
            )),
            1,
        )

    def test_editable_list_groups_by_location_and_add_button(self):
        result = self.env['presenly.approval.rule'].get_view(
            view_id=self.env.ref(
                'presenly.view_presenly_approval_rule_list_editable'
            ).id,
            view_type='list',
        )
        root = etree.fromstring(result['arch'].encode())
        list_node = root.xpath('//list')[0]
        self.assertEqual(list_node.get('default_group_by'), 'work_location_id')
        self.assertEqual(list_node.get('default_order'), 'sequence, id')
        self.assertEqual(
            len(root.xpath("//button[@name='action_add_next_level']")),
            1,
        )

    def test_form_has_add_next_level_button(self):
        result = self.env['presenly.approval.rule'].get_view(
            view_id=self.env.ref(
                'presenly.view_presenly_approval_rule_form'
            ).id,
            view_type='form',
        )
        root = etree.fromstring(result['arch'].encode())
        self.assertEqual(
            len(root.xpath("//button[@name='action_add_next_level']")),
            1,
        )

    def test_add_next_level_context_same_scope(self):
        action = self.leave_rule.action_add_next_level()
        ctx = action['context']
        self.assertEqual(ctx['default_company_id'], self.company.id)
        self.assertTrue(ctx['default_leave_type_id'])
        self.assertFalse(ctx['default_permission_type_id'])
        self.assertFalse(ctx['default_is_overtime_route'])
        self.assertEqual(ctx['default_approver_type'], 'employee_manager')
        self.assertEqual(ctx['default_name'], 'Level One — Next Level')
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['target'], 'new')

    def test_add_next_level_creates_next_order_via_form(self):
        self.assertEqual(self.leave_rule.sequence, 10)
        action = self.leave_rule.action_add_next_level()
        form = Form(
            self.env['presenly.approval.rule'].with_context(
                **action['context']
            ),
            view='presenly.view_presenly_approval_rule_form',
        )
        self.assertEqual(form.sequence, 20)
        form.name = 'Level Two'
        form.approver_type = 'hr'
        form.save()
        rules = self.env['presenly.approval.rule'].search([
            ('company_id', '=', self.company.id),
            ('leave_type_id', '=', self.leave_type.id),
        ], order='sequence')
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].sequence, 10)
        self.assertEqual(rules[1].sequence, 20)
        self.assertEqual(rules[1].name, 'Level Two')