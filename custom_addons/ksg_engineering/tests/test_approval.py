"""Tests Approval Consolidation — FR-008, FR-008A, RULE-05."""

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from datetime import date


class TestApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.ref('base.IDR')
        if not cls.currency:
            cls.currency = cls.env['res.currency'].create({
                'name': 'IDR', 'symbol': 'Rp', 'rounding': 1.0,
            })

        cls.partner = cls.env['res.partner'].create({'name': 'Client Approval'})
        cls.category = cls.env['ksg.sales.category'].create({'name': 'Cat Appr'})

        cls.checklist_wp = cls.env['ksg.sales.document.checklist'].create({
            'name': 'Working Permit',
        })
        cls.checklist_si = cls.env['ksg.sales.document.checklist'].create({
            'name': 'Safety Induction',
        })

        cls.project = cls.env['ksg.sales.project'].create({
            'klien': cls.partner.id,
            'kategori': cls.category.id,
            'nama_pekerjaan': 'Project Approval Test',
            'tanggal_po_diterima': date.today(),
            'no_pk': 'PO-APPR-001',
            'awal_kontrak': date(2026, 1, 1),
            'akhir_kontrak': date(2026, 12, 31),
            'currency_id': cls.currency.id,
            'nilai_kontrak_awal': 500000000,
            'sistem_penagihan': 'per_bulan',
            'checklist_dokumen_ids': [
                (4, cls.checklist_wp.id),
                (4, cls.checklist_si.id),
            ],
        })

        cls.wbs = cls.env['ksg.engineering.wbs'].create({
            'project_id': cls.project.id,
            'nama_pekerjaan': 'WBS Approval',
            'nilai_pekerjaan': 100000000,
            'tanggal_mulai': date(2026, 1, 1),
            'tanggal_selesai': date(2026, 6, 30),
        })

    def _create_submitted_daily_report(self):
        report = self.env['ksg.engineering.daily.report'].create({
            'project_id': self.project.id,
            'tanggal': date.today(),
        })
        self.env['ksg.engineering.daily.report.line'].create({
            'report_id': report.id,
            'wbs_id': self.wbs.id,
            'progress': 10.0,
            'deskripsi': 'Test approval',
        })
        report.action_submit()
        return report

    def test_consolidation_approve(self):
        """AC-003: state → approved."""
        dr = self._create_submitted_daily_report()
        cons = self.env['ksg.engineering.report.consolidation'].create({
            'project_id': self.project.id,
            'daily_report_ids': [(4, dr.id)],
        })
        cons.action_ajukan()
        self.assertEqual(cons.state, 'waiting_approval')
        cons.action_approve()
        self.assertEqual(cons.state, 'approved')

    def test_consolidation_revisi_requires_note(self):
        """AC-003B: revisi tanpa catatan → error (RULE-05)."""
        dr = self._create_submitted_daily_report()
        cons = self.env['ksg.engineering.report.consolidation'].create({
            'project_id': self.project.id,
            'daily_report_ids': [(4, dr.id)],
        })
        cons.action_ajukan()
        with self.assertRaises(ValidationError):
            cons.action_revisi()

    def test_consolidation_revisi_with_note(self):
        """Revisi dengan catatan → OK."""
        dr = self._create_submitted_daily_report()
        cons = self.env['ksg.engineering.report.consolidation'].create({
            'project_id': self.project.id,
            'daily_report_ids': [(4, dr.id)],
        })
        cons.action_ajukan()
        cons.catatan_revisi = 'Progress kurang detail, tambahkan foto.'
        cons.action_revisi()
        self.assertEqual(cons.state, 'revisi')

    def test_approve_not_from_waiting_raises(self):
        """Approve dari state draft → error."""
        dr = self._create_submitted_daily_report()
        cons = self.env['ksg.engineering.report.consolidation'].create({
            'project_id': self.project.id,
            'daily_report_ids': [(4, dr.id)],
        })
        with self.assertRaises(ValidationError):
            cons.action_approve()

    def test_consolidation_empty_raises(self):
        """Ajukan konsolidasi tanpa daily report → error."""
        cons = self.env['ksg.engineering.report.consolidation'].create({
            'project_id': self.project.id,
        })
        with self.assertRaises(ValidationError):
            cons.action_ajukan()
