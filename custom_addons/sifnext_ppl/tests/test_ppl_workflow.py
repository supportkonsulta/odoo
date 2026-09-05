from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("sifnext_ppl", "post_install", "-at_install")
class TestPPLWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env,
            login="ppl_user",
            groups="base.group_user",
            company_id=cls.env.company.id,
        )
        cls.other_user = new_test_user(
            cls.env,
            login="ppl_other",
            groups="base.group_user",
            company_id=cls.env.company.id,
        )
        cls.finance = new_test_user(
            cls.env,
            login="ppl_finance",
            groups="sifnext_ppl.group_ppl_finance",
            company_id=cls.env.company.id,
        )
        cls.director = new_test_user(
            cls.env,
            login="ppl_director",
            groups="sifnext_ppl.group_ppl_approver",
            company_id=cls.env.company.id,
        )
        cls.account = cls.env["account.account"].create({
            "name": "Biaya PPL Test",
            "code": "PPLTEST",
            "account_type": "expense",
            "company_ids": [Command.set(cls.env.company.ids)],
        })

    def _create_ppl(self):
        return self.env["sifnext.ppl"].with_user(self.user).create({
            "title": "Pengadaan alat tulis",
            "description": "Kebutuhan operasional",
            "line_ids": [Command.create({
                "description": "Alat tulis",
                "quantity": 2,
                "unit_price": 50_000,
            })],
        })

    def test_employee_submit_without_coa_then_finance_verify(self):
        ppl = self._create_ppl()
        self.assertEqual(ppl.applicant_id, self.user)
        self.assertEqual(ppl.source_type, "manual")
        self.assertEqual(ppl.total_amount, 100_000)
        self.assertNotEqual(ppl.name, "New")

        ppl.with_user(self.user).action_submit()
        self.assertEqual(ppl.state, "submitted")

        with self.assertRaises(AccessError):
            ppl.line_ids.with_user(self.user).write({"account_id": self.account.id})
        with self.assertRaises(ValidationError):
            ppl.with_user(self.finance).action_verify()

        ppl.line_ids.with_user(self.finance).write({"account_id": self.account.id})
        ppl.with_user(self.finance).action_verify()
        self.assertEqual(ppl.state, "verified")
        self.assertEqual(ppl.verified_by, self.finance)

    def test_finance_submission_skips_own_verification(self):
        ppl = self.env["sifnext.ppl"].with_user(self.finance).create({
            "title": "Pengajuan Keuangan",
            "description": "Langsung menunggu Direktur",
            "line_ids": [Command.create({
                "description": "Biaya operasional",
                "quantity": 1,
                "unit_price": 75_000,
                "account_id": self.account.id,
            })],
        })
        ppl.with_user(self.finance).action_submit()
        self.assertEqual(ppl.state, "verified")
        self.assertEqual(ppl.submitted_by, self.finance)
        self.assertEqual(ppl.verified_by, self.finance)
        self.assertTrue(ppl.submitted_at)
        self.assertEqual(ppl.verified_at, ppl.submitted_at)

    def test_finance_submission_requires_coa(self):
        ppl = self.env["sifnext.ppl"].with_user(self.finance).create({
            "title": "Pengajuan Keuangan tanpa COA",
            "description": "Harus ditolak",
            "line_ids": [Command.create({
                "description": "Biaya operasional",
                "quantity": 1,
                "unit_price": 75_000,
            })],
        })
        with self.assertRaises(ValidationError):
            ppl.with_user(self.finance).action_submit()
        self.assertEqual(ppl.state, "draft")

    def test_submitted_request_content_is_locked(self):
        ppl = self._create_ppl()
        ppl.with_user(self.user).action_submit()
        with self.assertRaises(UserError):
            ppl.with_user(self.user).write({"title": "Diubah"})
        with self.assertRaises(UserError):
            ppl.line_ids.with_user(self.finance).write({"unit_price": 1})

    def test_employee_cannot_impersonate_applicant(self):
        with self.assertRaises(AccessError):
            self.env["sifnext.ppl"].with_user(self.user).create({
                "applicant_id": self.other_user.id,
                "title": "Tidak valid",
                "description": "Tidak valid",
            })

    def test_employee_only_sees_own_requests(self):
        own_ppl = self._create_ppl()
        other_ppl = self.env["sifnext.ppl"].with_user(self.other_user).create({
            "title": "PPL user lain",
            "description": "Tidak boleh terlihat",
            "line_ids": [Command.create({
                "description": "Item",
                "quantity": 1,
                "unit_price": 10_000,
            })],
        })
        user_results = self.env["sifnext.ppl"].with_user(self.user).search([
            ("id", "in", (own_ppl | other_ppl).ids),
        ])
        finance_results = self.env["sifnext.ppl"].with_user(self.finance).search([
            ("id", "in", (own_ppl | other_ppl).ids),
        ])
        self.assertEqual(user_results, own_ppl)
        self.assertEqual(finance_results, own_ppl | other_ppl)

    def test_approval_payment_and_done_without_account_move(self):
        ppl = self._create_ppl()
        ppl.with_user(self.user).action_submit()
        ppl.line_ids.with_user(self.finance).write({"account_id": self.account.id})
        ppl.with_user(self.finance).action_verify()

        with self.assertRaises(AccessError):
            ppl.with_user(self.finance).action_approve()
        with self.assertRaises(AccessError):
            ppl.with_user(self.user).action_approve()
        with self.assertRaises(AccessError):
            ppl.with_user(self.user).write({"state": "done"})

        move_count = self.env["account.move"].search_count([])
        ppl.with_user(self.director).action_approve()
        self.assertEqual(ppl.state, "approved")
        self.assertEqual(ppl.approved_by, self.director)
        self.assertEqual(self.env["account.move"].search_count([]), move_count)

        with self.assertRaises(AccessError):
            ppl.with_user(self.director).action_pay()
        with self.assertRaises(ValidationError):
            ppl.with_user(self.finance).action_pay()
        ppl.with_user(self.finance).write({
            "payment_method": "bank",
            "payment_date": "2026-09-05",
            "payment_reference": "TRX-PPL-001",
        })
        ppl.with_user(self.finance).action_pay()
        self.assertEqual(ppl.state, "paid")
        self.assertEqual(ppl.paid_by, self.finance)
        self.assertEqual(self.env["account.move"].search_count([]), move_count)

        ppl.with_user(self.finance).action_done()
        self.assertEqual(ppl.state, "done")
        self.assertEqual(ppl.done_by, self.finance)
        with self.assertRaises(UserError):
            ppl.with_user(self.finance).action_done()

    def _prepare_approved_ppl(self):
        ppl = self._create_ppl()
        ppl.with_user(self.user).action_submit()
        ppl.line_ids.with_user(self.finance).write({"account_id": self.account.id})
        ppl.with_user(self.finance).action_verify()
        ppl.with_user(self.director).action_approve()
        ppl.with_user(self.finance).write({
            "payment_method": "bank",
            "payment_date": "2026-09-05",
            "payment_reference": "TRX-PPL-CONTRACT",
        })
        return ppl

    def test_paid_event_contract_and_dispatch_order(self):
        ppl = self._prepare_approved_ppl()
        calls = []

        def notify_rka(record, payload):
            calls.append(("rka", record.state, payload))
            return True

        def notify_general_ledger(record, payload):
            calls.append(("general_ledger", record.state, payload))
            return True

        model_class = type(ppl)
        with patch.object(model_class, "_notify_rka_paid", notify_rka), \
             patch.object(model_class, "_notify_general_ledger_paid", notify_general_ledger):
            ppl.with_user(self.finance).action_pay()

        self.assertEqual([call[0] for call in calls], ["rka", "general_ledger"])
        self.assertEqual([call[1] for call in calls], ["paid", "paid"])
        self.assertIs(calls[0][2], calls[1][2])
        payload = calls[0][2]
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["event"], "ppl.paid")
        self.assertEqual(payload["idempotency_key"], f"ppl.paid:{ppl.company_id.id}:{ppl.id}")
        self.assertEqual(payload["ppl"]["number"], ppl.name)
        self.assertEqual(payload["ppl"]["state"], "paid")
        self.assertEqual(payload["ppl"]["total_amount"], 100_000)
        self.assertEqual(payload["ppl"]["payment"]["reference"], "TRX-PPL-CONTRACT")
        self.assertEqual(payload["ppl"]["lines"][0]["account"]["code"], self.account.code)
        with self.assertRaises(UserError):
            ppl.with_user(self.finance).action_pay()
        self.assertEqual(len(calls), 2)

    def test_downstream_failure_rolls_back_payment(self):
        ppl = self._prepare_approved_ppl()

        def fail_general_ledger(record, payload):
            raise ValidationError("Jurnal Besar tidak tersedia")

        with self.assertRaises(ValidationError), self.cr.savepoint():
            with patch.object(type(ppl), "_notify_general_ledger_paid", fail_general_ledger):
                ppl.with_user(self.finance).action_pay()

        ppl.invalidate_recordset()
        self.assertEqual(ppl.state, "approved")
        self.assertFalse(ppl.paid_by)
        self.assertFalse(ppl.paid_at)

    def test_budget_check_uses_versioned_payload(self):
        ppl = self._create_ppl()
        ppl.with_user(self.user).action_submit()
        ppl.line_ids.with_user(self.finance).write({"account_id": self.account.id})
        payloads = []

        def validate_budget(record, payload):
            payloads.append(payload)
            return True

        with patch.object(type(ppl), "_validate_rka_budget", validate_budget):
            ppl.with_user(self.finance).action_verify()

        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["schema_version"], 1)
        self.assertEqual(payloads[0]["ppl_id"], ppl.id)
        self.assertEqual(payloads[0]["lines"][0]["account_id"], self.account.id)
        self.assertEqual(payloads[0]["lines"][0]["amount"], 100_000)

    def test_payment_data_is_restricted(self):
        ppl = self._create_ppl()
        with self.assertRaises(AccessError):
            ppl.with_user(self.user).write({"payment_reference": "INVALID"})
        with self.assertRaises(UserError):
            ppl.with_user(self.finance).write({"payment_reference": "TOO-EARLY"})

    def test_return_requires_reason(self):
        ppl = self._create_ppl()
        ppl.with_user(self.user).action_submit()
        with self.assertRaises(ValidationError):
            ppl.with_user(self.finance).action_return_to_draft()
        ppl.with_user(self.finance).with_context(return_reason="Nominal perlu diperbaiki").action_return_to_draft()
        self.assertEqual(ppl.state, "draft")
        self.assertEqual(ppl.return_reason, "Nominal perlu diperbaiki")
