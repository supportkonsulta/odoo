"""Tests WBS Engineering — FR-003, FR-004A, FR-005, FR-010, FR-011."""

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from datetime import date, timedelta


class TestWbs(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.ref('base.IDR')
        if not cls.currency:
            cls.currency = cls.env['res.currency'].create({
                'name': 'IDR', 'symbol': 'Rp', 'rounding': 1.0,
            })

        # Buat checklist master
        cls.checklist_wp = cls.env['ksg.sales.document.checklist'].create({
            'name': 'Working Permit',
        })
        cls.checklist_si = cls.env['ksg.sales.document.checklist'].create({
            'name': 'Safety Induction',
        })

        cls.partner = cls.env['res.partner'].create({'name': 'Test Client'})
        cls.category = cls.env['ksg.sales.category'].create({'name': 'Test Cat'})
        cls.project = cls.env['ksg.sales.project'].create({
            'klien': cls.partner.id,
            'kategori': cls.category.id,
            'nama_pekerjaan': 'Test Project WBS',
            'tanggal_po_diterima': date.today(),
            'no_pk': 'PO-001',
            'awal_kontrak': date(2026, 1, 1),
            'akhir_kontrak': date(2026, 12, 31),
            'currency_id': cls.currency.id,
            'nilai_kontrak_awal': 1000000000,
            'sistem_penagihan': 'per_bulan',
            'checklist_dokumen_ids': [
                (4, cls.checklist_wp.id),
                (4, cls.checklist_si.id),
            ],
        })

    def test_wbs_bobot_compute(self):
        """FR-005, RULE-04: bobot = nilai_pekerjaan / nilai_kontrak × 100."""
        wbs = self.env['ksg.engineering.wbs'].create({
            'project_id': self.project.id,
            'nama_pekerjaan': 'Pekerjaan A',
            'nilai_pekerjaan': 200000000,
            'tanggal_mulai': date(2026, 1, 1),
            'tanggal_selesai': date(2026, 6, 30),
        })
        self.assertAlmostEqual(wbs.bobot, 20.0, places=2)

    def test_wbs_outside_period_raises(self):
        """FR-004A: tanggal di luar periode kontrak → ValidationError."""
        with self.assertRaises(ValidationError):
            self.env['ksg.engineering.wbs'].create({
                'project_id': self.project.id,
                'nama_pekerjaan': 'Pekerjaan Luar Periode',
                'nilai_pekerjaan': 100000000,
                'tanggal_mulai': date(2025, 1, 1),
                'tanggal_selesai': date(2025, 6, 30),
            })

    def test_wbs_otorisasi_luar_periode(self):
        """FR-004A: dengan otorisasi + alasan → OK."""
        wbs = self.env['ksg.engineering.wbs'].create({
            'project_id': self.project.id,
            'nama_pekerjaan': 'Pekerjaan Override',
            'nilai_pekerjaan': 50000000,
            'tanggal_mulai': date(2025, 6, 1),
            'tanggal_selesai': date(2025, 12, 31),
            'otorisasi_luar_periode': True,
            'alasan_luar_periode': 'Pekerjaan persiapan sebelum kontrak dimulai.',
        })
        self.assertTrue(wbs.id)

    def test_wbs_otorisasi_without_reason_raises(self):
        """FR-004A: otorisasi tanpa alasan → ValidationError."""
        with self.assertRaises(ValidationError):
            self.env['ksg.engineering.wbs'].create({
                'project_id': self.project.id,
                'nama_pekerjaan': 'Pekerjaan Override No Reason',
                'nilai_pekerjaan': 50000000,
                'tanggal_mulai': date(2025, 6, 1),
                'tanggal_selesai': date(2025, 12, 31),
                'otorisasi_luar_periode': True,
            })

    def test_bobot_recompute_on_addendum(self):
        """FR-005, RULE-04: perubahan nilai kontrak → bobot recompute."""
        wbs = self.env['ksg.engineering.wbs'].create({
            'project_id': self.project.id,
            'nama_pekerjaan': 'Pekerjaan Addendum',
            'nilai_pekerjaan': 200000000,
            'tanggal_mulai': date(2026, 1, 1),
            'tanggal_selesai': date(2026, 6, 30),
        })
        self.assertAlmostEqual(wbs.bobot, 20.0, places=2)

        # Simulasi addendum: nilai kontrak naik
        self.env['ksg.sales.project.addendum'].create({
            'project_id': self.project.id,
            'nama_addendum': 'Addendum 1',
            'nilai_addendum': 500000000,
            'tanggal_addendum': date.today(),
        })
        wbs.invalidate_recordset()
        # bobot seharusnya berubah setelah recompute
        # nilai_kontrak_terkini = 1000000000 + 500000000 = 1500000000
        # bobot = 200000000 / 1500000000 * 100 = 13.33
        self.assertAlmostEqual(wbs.bobot, 13.33, places=1)

    def test_calendar_weeks(self):
        """FR-011: kalender minggu terbentuk dari awal/akhir kontrak."""
        self.project.action_generate_calendar_weeks()
        weeks = self.env['ksg.engineering.schedule.week'].search([
            ('project_id', '=', self.project.id)
        ])
        self.assertTrue(len(weeks) > 0)
        # 2026 has 365 days, ceil(365/7) = 53 weeks approximately
        self.assertGreaterEqual(len(weeks), 52)
