"""Tests BAP/BAST — FR-014, FR-014A, RULE-08, RULE-09."""

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from datetime import date


class TestBapbast(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.ref('base.IDR')
        if not cls.currency:
            cls.currency = cls.env['res.currency'].create({
                'name': 'IDR', 'symbol': 'Rp', 'rounding': 1.0,
            })

        cls.partner = cls.env['res.partner'].create({'name': 'Client BAPBAST'})
        cls.category = cls.env['ksg.sales.category'].create({'name': 'Cat BAP'})
        cls.project = cls.env['ksg.sales.project'].create({
            'klien': cls.partner.id,
            'kategori': cls.category.id,
            'nama_pekerjaan': 'Project BAPBAST',
            'tanggal_po_diterima': date.today(),
            'no_pk': 'PO-BAP-001',
            'awal_kontrak': date(2026, 1, 1),
            'akhir_kontrak': date(2026, 12, 31),
            'currency_id': cls.currency.id,
            'nilai_kontrak_awal': 500000000,
            'sistem_penagihan': 'per_bulan',
        })

    def test_bapbast_sequence(self):
        """BAP/BAST memiliki nomor sequence."""
        bap = self.env['ksg.engineering.bapbast'].create({
            'project_id': self.project.id,
            'periode': 'Januari 2026',
        })
        self.assertNotEqual(bap.name, 'New')
        self.assertTrue(bap.name.startswith('BAPBAST/'))

    def test_bapbast_approval_workflow(self):
        """FR-014: workflow draft → waiting → approved."""
        bap = self.env['ksg.engineering.bapbast'].create({
            'project_id': self.project.id,
            'periode': 'Februari 2026',
        })
        self.assertEqual(bap.state, 'draft')

        bap.action_ajukan()
        self.assertEqual(bap.state, 'waiting_approval')

        bap.action_approve()
        self.assertEqual(bap.state, 'approved')
        self.assertTrue(bap.approver_id)
        self.assertTrue(bap.tanggal_approve)

    def test_bapbast_approve_not_from_waiting_raises(self):
        """RULE-09: approve hanya dari waiting_approval."""
        bap = self.env['ksg.engineering.bapbast'].create({
            'project_id': self.project.id,
            'periode': 'Maret 2026',
        })
        with self.assertRaises(ValidationError):
            bap.action_approve()

    def test_bapbast_approved_flag(self):
        """FR-014A: bapbast_approved = True saat ada BAP/BAST approved."""
        self.assertFalse(self.project.bapbast_approved)
        bap = self.env['ksg.engineering.bapbast'].create({
            'project_id': self.project.id,
            'periode': 'April 2026',
        })
        bap.action_ajukan()
        bap.action_approve()
        self.project.invalidate_recordset()
        self.assertTrue(self.project.bapbast_approved)

    def test_bapbast_ajukan_not_from_draft_raises(self):
        """Ajukan hanya dari draft."""
        bap = self.env['ksg.engineering.bapbast'].create({
            'project_id': self.project.id,
            'periode': 'Mei 2026',
        })
        bap.action_ajukan()
        with self.assertRaises(ValidationError):
            bap.action_ajukan()
