"""Tests Daily Report — FR-006, FR-006A, FR-007, RULE-02."""

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from datetime import date


class TestDailyReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.ref('base.IDR')
        if not cls.currency:
            cls.currency = cls.env['res.currency'].create({
                'name': 'IDR', 'symbol': 'Rp', 'rounding': 1.0,
            })

        cls.partner = cls.env['res.partner'].create({'name': 'Test Client DR'})
        cls.category = cls.env['ksg.sales.category'].create({'name': 'Cat DR'})

        # Project TANPA checklist WP/SI
        cls.project_no_permit = cls.env['ksg.sales.project'].create({
            'klien': cls.partner.id,
            'kategori': cls.category.id,
            'nama_pekerjaan': 'Project No Permit',
            'tanggal_po_diterima': date.today(),
            'no_pk': 'PO-DR-001',
            'awal_kontrak': date(2026, 1, 1),
            'akhir_kontrak': date(2026, 12, 31),
            'currency_id': cls.currency.id,
            'nilai_kontrak_awal': 500000000,
            'sistem_penagihan': 'per_bulan',
        })

        # Project DENGAN checklist WP/SI
        cls.checklist_wp = cls.env['ksg.sales.document.checklist'].create({
            'name': 'Working Permit',
        })
        cls.checklist_si = cls.env['ksg.sales.document.checklist'].create({
            'name': 'Safety Induction',
        })
        cls.project_with_permit = cls.env['ksg.sales.project'].create({
            'klien': cls.partner.id,
            'kategori': cls.category.id,
            'nama_pekerjaan': 'Project With Permit',
            'tanggal_po_diterima': date.today(),
            'no_pk': 'PO-DR-002',
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
            'project_id': cls.project_with_permit.id,
            'nama_pekerjaan': 'Item WBS DR',
            'nilai_pekerjaan': 100000000,
            'tanggal_mulai': date(2026, 1, 1),
            'tanggal_selesai': date(2026, 6, 30),
        })

    def test_daily_report_blocked_without_permit(self):
        """AC-002B: submit ditolak jika working_permit_ok=False."""
        report = self.env['ksg.engineering.daily.report'].create({
            'project_id': self.project_no_permit.id,
            'tanggal': date.today(),
        })
        # Tambah line
        self.env['ksg.engineering.daily.report.line'].create({
            'report_id': report.id,
            'wbs_id': self.env['ksg.engineering.wbs'].create({
                'project_id': self.project_no_permit.id,
                'nama_pekerjaan': 'Item No Permit',
                'nilai_pekerjaan': 100000000,
                'tanggal_mulai': date(2026, 1, 1),
                'tanggal_selesai': date(2026, 6, 30),
            }).id,
            'progress': 10.0,
            'deskripsi': 'Test no permit',
        })
        with self.assertRaises(ValidationError):
            report.action_submit()

    def test_daily_report_success(self):
        """AC-002: submit berhasil jika permit OK."""
        report = self.env['ksg.engineering.daily.report'].create({
            'project_id': self.project_with_permit.id,
            'tanggal': date.today(),
        })
        self.env['ksg.engineering.daily.report.line'].create({
            'report_id': report.id,
            'wbs_id': self.wbs.id,
            'progress': 15.0,
            'deskripsi': 'Pekerjaan berjalan lancar',
        })
        report.action_submit()
        self.assertEqual(report.state, 'submitted')

    def test_daily_report_empty_line_raises(self):
        """Submit tanpa line → error."""
        report = self.env['ksg.engineering.daily.report'].create({
            'project_id': self.project_with_permit.id,
            'tanggal': date.today(),
        })
        with self.assertRaises(ValidationError):
            report.action_submit()
