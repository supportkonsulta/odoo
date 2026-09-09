from odoo.tests.common import TransactionCase


class TestPresenlyApprovalAutoOrder(TransactionCase):
    """Approval Route Order is assigned automatically at creation.

    Steps in the same scope get 10, 20, 30, ... so later steps can be
    inserted in between. Explicit Orders (tests, API, bulk creation) are
    always respected.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.permission_type = cls.env['presenly.permission.type'].create({
            'name': 'Auto Order Permission',
            'code': 'AUTO_ORDER',
            'company_id': cls.company.id,
            'request_mode': 'full_day',
            'paid_status': 'policy',
        })

    def _rule(self, **overrides):
        values = {
            'name': overrides.pop('name', 'Auto Order Step'),
            'company_id': self.company.id,
            'permission_type_id': self.permission_type.id,
            'approver_type': 'employee_manager',
        }
        values.update(overrides)
        return self.env['presenly.approval.rule'].create(values)

    def test_two_steps_same_scope_get_10_and_20(self):
        first = self._rule(name='First Step')
        second = self._rule(name='Second Step')
        self.assertEqual(first.sequence, 10)
        self.assertEqual(second.sequence, 20)

    def test_third_step_gets_30(self):
        self._rule(name='First Step')
        self._rule(name='Second Step')
        third = self._rule(name='Third Step')
        self.assertEqual(third.sequence, 30)

    def test_explicit_sequence_is_kept_and_next_is_after_it(self):
        explicit = self._rule(name='Explicit Step', sequence=30)
        self.assertEqual(explicit.sequence, 30)
        auto = self._rule(name='Auto After Explicit')
        self.assertEqual(auto.sequence, 40)

    def test_different_scopes_both_start_at_10(self):
        other_type = self.env['presenly.permission.type'].create({
            'name': 'Other Permission',
            'code': 'OTHER_ORDER',
            'company_id': self.company.id,
            'request_mode': 'full_day',
            'paid_status': 'policy',
        })
        first = self._rule(name='Scope A')
        second = self.env['presenly.approval.rule'].create({
            'name': 'Scope B',
            'company_id': self.company.id,
            'permission_type_id': other_type.id,
            'approver_type': 'employee_manager',
        })
        self.assertEqual(first.sequence, 10)
        self.assertEqual(second.sequence, 10)

    def test_batch_create_auto_sequence(self):
        created = self.env['presenly.approval.rule'].create([
            {
                'name': 'Batch 1',
                'company_id': self.company.id,
                'permission_type_id': self.permission_type.id,
                'approver_type': 'employee_manager',
            },
            {
                'name': 'Batch 2',
                'company_id': self.company.id,
                'permission_type_id': self.permission_type.id,
                'approver_type': 'employee_manager',
            },
            {
                'name': 'Batch 3',
                'company_id': self.company.id,
                'permission_type_id': self.permission_type.id,
                'approver_type': 'employee_manager',
            },
        ])
        self.assertEqual(created[0].sequence, 10)
        self.assertEqual(created[1].sequence, 20)
        self.assertEqual(created[2].sequence, 30)

    def test_default_get_previews_next_sequence(self):
        defaults = self.env['presenly.approval.rule'].with_context(
            default_company_id=self.company.id,
            default_permission_type_id=self.permission_type.id,
        ).default_get(['sequence'])
        self.assertEqual(defaults['sequence'], 10)
        self._rule(name='Existing Step')
        defaults = self.env['presenly.approval.rule'].with_context(
            default_company_id=self.company.id,
            default_permission_type_id=self.permission_type.id,
        ).default_get(['sequence'])
        self.assertEqual(defaults['sequence'], 20)

    def test_work_location_scope_is_isolated(self):
        def _location(name):
            address = self.env['res.partner'].create({
                'name': name,
                'company_id': self.company.id,
            })
            return self.env['hr.work.location'].create({
                'name': name,
                'company_id': self.company.id,
                'address_id': address.id,
            })
        location_a = _location('Auto Loc A')
        location_b = _location('Auto Loc B')
        first = self._rule(name='Loc A step', work_location_id=location_a.id)
        second = self._rule(name='Loc B step', work_location_id=location_b.id)
        self.assertEqual(first.sequence, 10)
        self.assertEqual(second.sequence, 10)