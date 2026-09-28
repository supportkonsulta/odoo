from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPresenlySaasGuard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.guard = cls.env['presenly.saas.guard']

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True,
            'base_url': 'https://saas.example.com',
            'tenant_code': 'demo',
            'api_key': 'secret-key',
            'guard_mode': 'enforce',
            'grace_days': 7,
        })
        self.env['presenly.saas.subscription'].search([]).unlink()

    def snapshot(self, **overrides):
        values = {
            'company_id': self.company.id,
            'config_id': self.config.id,
            'tenant_code': 'demo',
            'plan_type': 'premium',
            'status': 'active',
            'state_source': 'live',
            'last_sync_at': fields.Datetime.now(),
            'current_period_end': fields.Datetime.now() + timedelta(days=30),
        }
        values.update(overrides)
        return self.env['presenly.saas.subscription'].create(values)

    # ------------------------------------------------------------------
    # Nothing enabled means nothing is blocked
    # ------------------------------------------------------------------
    def test_disabled_connection_always_allows(self):
        self.config.enabled = False
        self.snapshot(status='expired')
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))
        self.assertEqual(self.guard.state()['effective_state'], 'allowed')

    def test_off_mode_allows_even_an_expired_subscription(self):
        self.config.guard_mode = 'off'
        self.snapshot(status='expired')
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))

    def test_warn_mode_allows_even_an_expired_subscription(self):
        self.config.guard_mode = 'warn'
        self.snapshot(status='expired')
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))

    def test_without_a_snapshot_nothing_is_blocked(self):
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))
        self.assertFalse(self.guard.state()['has_snapshot'])

    # ------------------------------------------------------------------
    # Enforce
    # ------------------------------------------------------------------
    def test_enforce_blocks_a_reported_expiry(self):
        self.snapshot(status='expired')
        self.assertFalse(self.guard.is_allowed('attendance.check_in'))
        with self.assertRaises(UserError):
            self.guard.check('attendance.check_in')

    def test_enforce_blocks_a_suspended_subscription(self):
        self.snapshot(status='suspended')
        with self.assertRaises(UserError):
            self.guard.check('overtime.create')

    def test_enforce_blocks_an_ended_trial(self):
        self.snapshot(
            status='trial',
            is_trial=True,
            trial_ends_at=fields.Datetime.now() - timedelta(days=1),
        )
        with self.assertRaises(UserError):
            self.guard.check('leave.create')

    def test_enforce_allows_an_active_trial(self):
        self.snapshot(
            status='trial',
            is_trial=True,
            trial_ends_at=fields.Datetime.now() + timedelta(days=5),
        )
        self.assertTrue(self.guard.is_allowed('leave.create'))

    def test_enforce_allows_an_active_subscription(self):
        self.snapshot(status='active')
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))

    def test_skip_context_bypasses_the_guard(self):
        self.snapshot(status='expired')
        guard = self.guard.with_context(presenly_saas_skip_guard=True)
        self.assertTrue(guard.is_allowed('attendance.check_in'))

    # ------------------------------------------------------------------
    # A network failure never blocks
    # ------------------------------------------------------------------
    def test_cached_snapshot_is_allowed_inside_the_grace_period(self):
        self.snapshot(
            status='expired',
            state_source='cached',
            last_sync_at=fields.Datetime.now() - timedelta(days=1),
        )
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))

    def test_cached_snapshot_is_still_allowed_after_the_grace_period(self):
        # The status was never re-confirmed, so the module has no business
        # blocking on it. Only a real answer from the SaaS server may block.
        self.snapshot(
            status='expired',
            state_source='cached',
            last_sync_at=fields.Datetime.now() - timedelta(days=60),
        )
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))

    def test_unreachable_snapshot_is_allowed(self):
        self.snapshot(status='expired', state_source='unreachable')
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))

    # ------------------------------------------------------------------
    # Full access policy
    # ------------------------------------------------------------------
    def test_features_are_always_granted(self):
        for code in ('attendance', 'overtime', 'leave', 'anything-at-all'):
            self.assertTrue(self.guard.has_feature(code))

    # ------------------------------------------------------------------
    # Banner payload
    # ------------------------------------------------------------------
    def test_banner_hidden_when_the_connection_is_off(self):
        self.config.enabled = False
        self.snapshot(status='expired')
        self.assertFalse(self.env['presenly.saas.subscription'].get_banner_payload()['visible'])

    def test_banner_hidden_in_off_mode(self):
        self.config.guard_mode = 'off'
        self.snapshot(status='expired')
        self.assertFalse(self.env['presenly.saas.subscription'].get_banner_payload()['visible'])

    def test_banner_hidden_when_banner_is_turned_off(self):
        self.config.show_banner = False
        self.snapshot(status='expired')
        self.assertFalse(self.env['presenly.saas.subscription'].get_banner_payload()['visible'])

    def test_banner_hidden_for_a_healthy_subscription(self):
        self.snapshot(status='active')
        self.assertFalse(self.env['presenly.saas.subscription'].get_banner_payload()['visible'])

    def test_banner_hidden_for_a_trial_that_has_weeks_left(self):
        # Masa uji 30 hari tidak boleh menahan banner terus-menerus; kalau
        # begitu orang belajar mengabaikannya sebelum masalahnya datang.
        self.snapshot(
            status='trial',
            is_trial=True,
            trial_ends_at=fields.Datetime.now() + timedelta(days=27),
        )
        self.assertFalse(self.env['presenly.saas.subscription'].get_banner_payload()['visible'])

    def test_banner_warns_when_the_trial_is_almost_over(self):
        self.snapshot(
            status='trial',
            is_trial=True,
            trial_ends_at=fields.Datetime.now() + timedelta(days=3),
        )
        payload = self.env['presenly.saas.subscription'].get_banner_payload()
        self.assertTrue(payload['visible'])
        self.assertEqual(payload['severity'], 'warning')

    def test_banner_is_red_once_the_trial_has_ended(self):
        self.snapshot(
            status='trial',
            is_trial=True,
            trial_ends_at=fields.Datetime.now() - timedelta(days=1),
        )
        payload = self.env['presenly.saas.subscription'].get_banner_payload()
        self.assertEqual(payload['severity'], 'danger')

    def test_banner_reports_danger_for_an_expired_subscription(self):
        self.snapshot(status='expired')
        payload = self.env['presenly.saas.subscription'].get_banner_payload()
        self.assertTrue(payload['visible'])
        self.assertEqual(payload['severity'], 'danger')
        self.assertEqual(payload['status_label'], 'Expired')

    def test_banner_reports_warning_when_the_server_could_not_be_reached(self):
        self.snapshot(status='active', state_source='unreachable')
        payload = self.env['presenly.saas.subscription'].get_banner_payload()
        self.assertEqual(payload['severity'], 'warning')

    def test_banner_warns_before_a_paid_period_ends(self):
        self.snapshot(
            status='active',
            current_period_end=fields.Datetime.now() + timedelta(days=3),
        )
        payload = self.env['presenly.saas.subscription'].get_banner_payload()
        self.assertEqual(payload['severity'], 'warning')

    def test_banner_payload_never_carries_the_api_key(self):
        self.snapshot(status='expired')
        payload = self.env['presenly.saas.subscription'].get_banner_payload()
        self.assertNotIn('secret-key', str(payload))

    # ------------------------------------------------------------------
    # Guard mode changes
    # ------------------------------------------------------------------
    def test_switching_to_enforce_takes_effect_immediately(self):
        self.config.guard_mode = 'enforce'
        self.snapshot(status='expired')
        self.assertFalse(self.guard.is_allowed('attendance.check_in'))
        self.config.guard_mode = 'warn'
        self.assertTrue(self.guard.is_allowed('attendance.check_in'))
