from unittest.mock import Mock, patch

import requests

from odoo.tests.common import BaseCase

from ..services.saas_client import PresenlySaasClient, SaasClientError

API_KEY = "super-secret-key"


def make_response(status_code=200, json_body=None, raise_json=False):
    response = Mock()
    response.status_code = status_code
    if raise_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = json_body
    return response


class TestPresenlySaasClient(BaseCase):
    def setUp(self):
        super().setUp()
        self.client = PresenlySaasClient(
            base_url="https://saas.example.com",
            api_key=API_KEY,
            tenant_code="demo",
            timeout=5,
            retry_count=2,
        )

    # ------------------------------------------------------------------
    # URL and headers
    # ------------------------------------------------------------------
    def test_endpoint_appends_the_external_prefix(self):
        self.assertEqual(
            self.client._endpoint("/v1/subscription"),
            "https://saas.example.com/api/external/v1/subscription",
        )

    def test_endpoint_accepts_a_base_url_that_already_ends_with_api(self):
        client = PresenlySaasClient("https://saas.example.com/api/", API_KEY, "demo")
        self.assertEqual(
            client._endpoint("/v1/subscription"),
            "https://saas.example.com/api/external/v1/subscription",
        )

    def test_headers_carry_the_api_key_and_the_tenant(self):
        headers = self.client._headers()
        self.assertEqual(headers["X-API-Key"], API_KEY)
        self.assertEqual(headers["X-Tenant-ID"], "demo")

    # ------------------------------------------------------------------
    # Success
    # ------------------------------------------------------------------
    def test_get_subscription_returns_the_data_object(self):
        body = {"success": True, "data": {"status": "active", "schema_version": "1.0.0"}}
        with patch("requests.request", return_value=make_response(200, body)) as get:
            data = self.client.get_subscription()
        self.assertEqual(data["status"], "active")
        self.assertTrue(get.call_args.kwargs["verify"])

    # ------------------------------------------------------------------
    # Failures
    # ------------------------------------------------------------------
    def test_unauthorized_is_not_retried(self):
        body = {"success": False, "message": "Invalid or missing API Key"}
        with patch("requests.request", return_value=make_response(401, body)) as get:
            with self.assertRaises(SaasClientError) as ctx:
                self.client.get_subscription()
        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")
        self.assertEqual(get.call_count, 1)

    def test_server_error_is_retried_then_raised(self):
        body = {"success": False, "message": "boom"}
        with patch("requests.request", return_value=make_response(503, body)) as get:
            with patch("time.sleep"):
                with self.assertRaises(SaasClientError) as ctx:
                    self.client.get_subscription()
        self.assertEqual(ctx.exception.http_status, 503)
        self.assertEqual(get.call_count, 3)

    def test_server_error_recovers_on_a_later_attempt(self):
        body = {"success": True, "data": {"status": "trial", "schema_version": "1.0.0"}}
        responses = [make_response(503, {}), make_response(200, body)]
        with patch("requests.request", side_effect=responses):
            with patch("time.sleep"):
                data = self.client.get_subscription()
        self.assertEqual(data["status"], "trial")

    def test_network_error_is_reported_as_such(self):
        with patch("requests.request", side_effect=requests.ConnectionError("refused")):
            with patch("time.sleep"):
                with self.assertRaises(SaasClientError) as ctx:
                    self.client.get_subscription()
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")

    def test_unparsable_body_is_rejected(self):
        with patch("requests.request", return_value=make_response(200, raise_json=True)):
            with self.assertRaises(SaasClientError) as ctx:
                self.client.get_subscription()
        self.assertEqual(ctx.exception.code, "BAD_PAYLOAD")

    def test_unsupported_schema_version_is_rejected(self):
        body = {"success": True, "data": {"schema_version": "99.0.0"}}
        with patch("requests.request", return_value=make_response(200, body)):
            with self.assertRaises(SaasClientError) as ctx:
                self.client.get_subscription()
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_SCHEMA")

    def test_missing_schema_version_is_accepted(self):
        body = {"success": True, "data": {"status": "active"}}
        with patch("requests.request", return_value=make_response(200, body)):
            data = self.client.get_subscription()
        self.assertEqual(data["status"], "active")

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------
    def test_api_key_never_appears_in_the_error_message(self):
        with patch(
            "requests.request",
            side_effect=requests.ConnectionError(f"failed to reach {API_KEY}"),
        ):
            with patch("time.sleep"):
                with self.assertRaises(SaasClientError) as ctx:
                    self.client.get_subscription()
        self.assertNotIn(API_KEY, str(ctx.exception))
