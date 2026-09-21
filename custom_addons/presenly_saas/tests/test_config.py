from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.saas_client import PresenlySaasClient, SaasClientError

CLIENT_PATH = "odoo.addons.presenly_saas.models.presenly_saas_config.PresenlySaasClient"


@tagged('post_install', '-at_install')
class TestPresenlySaasConfig(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.config.write({
            'enabled': True,
            'base_url': 'https://saas.example.com',
            'tenant_code': 'demo',
            'api_key': 'secret-key',
            'retry_count': 0,
        })

    @staticmethod
    def payload(**overrides):
        data = {
            'tenant_code': 'demo',
            'client_name': 'Demo Tenant',
            'plan_type': 'premium',
            'status': 'active',
            'is_trial': False,
            'trial_ends_at': None,
            'current_period_end': '2099-01-01T00:00:00.000Z',
            'seat_limit': 50,
            'seats_used': 10,
            'price_per_user': 30000,
            'schema_version': '1.0.0',
            'server_time': '2026-09-18T10:05:00.000Z',
        }
        data.update(overrides)
        return data

    def subscription(self):
        return self.env['presenly.saas.subscription'].search(
            [('company_id', '=', self.company.id)], limit=1
        )

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------
    def test_get_or_create_returns_one_record_per_company(self):
        first = self.env['presenly.saas.config']._get_or_create(self.company)
        second = self.env['presenly.saas.config']._get_or_create(self.company)
        self.assertEqual(first, second)
        count = self.env['presenly.saas.config'].search_count(
            [('company_id', '=', self.company.id)]
        )
        self.assertEqual(count, 1)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def test_base_url_must_be_absolute(self):
        with self.assertRaises(UserError):
            self.config.base_url = 'saas.example.com'

    def test_timeout_must_be_positive(self):
        with self.assertRaises(UserError):
            self.config.timeout_seconds = 0

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def test_refresh_stores_the_snapshot_and_writes_one_log_entry(self):
        with patch.object(PresenlySaasClient, 'get_subscription', return_value=self.payload()):
            self.config.action_refresh_subscription()

        subscription = self.subscription()
        self.assertTrue(subscription)
        self.assertEqual(subscription.status, 'active')
        self.assertEqual(subscription.plan_type, 'premium')
        self.assertEqual(subscription.state_source, 'live')
        self.assertEqual(subscription.seats_used, 10)
        self.assertEqual(subscription.seat_limit, 50)
        self.assertEqual(self.config.last_check_status, 'success')

        logs = self.env['presenly.saas.sync.log'].search(
            [('company_id', '=', self.company.id)]
        )
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs.success)
        self.assertEqual(logs.endpoint, '/api/external/v1/subscription')

    def test_refresh_refuses_to_run_while_disabled(self):
        self.config.enabled = False
        with self.assertRaises(UserError):
            self.config.action_refresh_subscription()

    def test_refresh_requires_credentials(self):
        self.config.api_key = False
        with self.assertRaises(UserError):
            self.config.action_refresh_subscription()

    # ------------------------------------------------------------------
    # A failed pull must never rewrite the status
    # ------------------------------------------------------------------
    def test_failed_refresh_keeps_the_status_and_marks_the_snapshot_cached(self):
        with patch.object(PresenlySaasClient, 'get_subscription', return_value=self.payload()):
            self.config.action_refresh_subscription()

        error = SaasClientError("Tidak dapat menghubungi server Presenly SaaS.", code="NETWORK_ERROR")
        with patch.object(PresenlySaasClient, 'get_subscription', side_effect=error):
            result = self.config.action_refresh_subscription()

        subscription = self.subscription()
        self.assertEqual(subscription.status, 'active')
        self.assertEqual(subscription.state_source, 'cached')
        self.assertEqual(self.config.last_check_status, 'failed')
        self.assertIn('Tidak dapat menghubungi', self.config.last_check_message)

        logs = self.env['presenly.saas.sync.log'].search(
            [('company_id', '=', self.company.id)], order='id desc', limit=1
        )
        self.assertFalse(logs.success)

        # A remote failure is reported to the user, not raised: an exception
        # reaching the RPC layer would roll the diagnostics back with it.
        self.assertEqual(result['params']['type'], 'danger')
        self.assertEqual(result['params']['title'], 'Refresh failed')

    def test_failed_first_refresh_leaves_the_snapshot_unreachable(self):
        error = SaasClientError("Tidak dapat menghubungi server Presenly SaaS.", code="NETWORK_ERROR")
        with patch.object(PresenlySaasClient, 'get_subscription', side_effect=error):
            result = self.config.action_refresh_subscription()
        self.assertEqual(result['params']['type'], 'danger')
        self.assertEqual(self.config.last_check_status, 'failed')
        self.assertFalse(self.subscription())

    def test_successful_actions_report_a_success_notification(self):
        with patch.object(PresenlySaasClient, 'get_subscription', return_value=self.payload()):
            test_result = self.config.action_test_connection()
            refresh_result = self.config.action_refresh_subscription()
        self.assertEqual(test_result['params']['type'], 'success')
        self.assertEqual(refresh_result['params']['type'], 'success')

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def test_unknown_status_from_the_server_is_stored_as_unknown(self):
        with patch.object(
            PresenlySaasClient, 'get_subscription', return_value=self.payload(status='weird')
        ):
            self.config.action_refresh_subscription()
        self.assertEqual(self.subscription().status, 'unknown')

    def test_summary_never_leaks_the_api_key(self):
        with patch.object(PresenlySaasClient, 'get_subscription', return_value=self.payload()):
            self.config.action_refresh_subscription()
        self.assertNotIn('secret-key', self.config.last_check_message or '')

    def test_summary_shows_the_trial_end_when_no_paid_period_exists(self):
        # Tenant masa uji mengirim trial_ends_at dan current_period_end null.
        # Tanpa ini, ringkasan terlihat seperti langganan yang tidak berakhir.
        with patch.object(
            PresenlySaasClient,
            'get_subscription',
            return_value=self.payload(
                status='trial',
                is_trial=True,
                trial_ends_at='2026-10-17T15:57:50.000Z',
                current_period_end=None,
            ),
        ):
            self.config.action_refresh_subscription()
        self.assertIn('2026-10-17', self.config.last_check_message or '')

    def test_summary_shows_the_paid_period_end_when_present(self):
        with patch.object(
            PresenlySaasClient,
            'get_subscription',
            return_value=self.payload(current_period_end='2026-11-05T00:00:00.000Z'),
        ):
            self.config.action_refresh_subscription()
        self.assertIn('2026-11-05', self.config.last_check_message or '')

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    def test_cron_refreshes_enabled_connections_and_survives_failures(self):
        error = SaasClientError("down", code="NETWORK_ERROR")
        with patch.object(PresenlySaasClient, 'get_subscription', side_effect=error):
            self.env['presenly.saas.config']._cron_refresh_all()
        self.assertEqual(self.config.last_check_status, 'failed')

    def test_cron_prunes_old_log_entries(self):
        log = self.env['presenly.saas.sync.log']._record(
            self.company, '/api/external/v1/subscription', success=True
        )
        self.env.cr.execute(
            "UPDATE presenly_saas_sync_log SET create_date = now() - interval '200 days' WHERE id = %s",
            (log.id,),
        )
        self.env['presenly.saas.sync.log']._prune()
        self.assertFalse(log.exists())
