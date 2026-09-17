# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PendapatanLaporanWizard(models.TransientModel):
    _name = 'pendapatan.laporan.wizard'
    _description = 'Wizard Filter Laporan Pendapatan'

    date_from = fields.Date(
        string='Tanggal Awal',
        required=False
    )
    date_to = fields.Date(
        string='Tanggal Akhir',
        required=False
    )
    category_id = fields.Many2one(
        'pendapatan.category',
        string='Kategori (Opsional)',
        required=False
    )
    unit_name = fields.Char(
        string='Unit Kerja (Opsional)',
        required=False
    )
    state = fields.Selection([
        ('all', 'Semua Status'),
        ('posted', 'Terposting Saja'),
        ('draft', 'Draft Saja'),
        ('submitted', 'Diajukan Saja'),
        ('approved', 'Disetujui Saja'),
        ('cancelled', 'Dibatalkan Saja'),
    ], string='Status', required=True, default='posted')
    group_by = fields.Selection([
        ('category', 'Per Kategori'),
        ('unit', 'Per Unit Kerja'),
        ('date_month', 'Per Bulan'),
    ], string='Kelompokkan Berdasarkan', required=True, default='category')

    def action_tampilkan_laporan(self):
        self.ensure_one()
        domain = []

        # Status filter
        if self.state == 'all':
            pass
        elif self.state == 'posted':
            domain.append(('state', '=', 'posted'))
        else:
            domain.append(('state', '=', self.state))

        if self.date_from:
            domain.append(('tanggal', '>=', self.date_from))
        if self.date_to:
            domain.append(('tanggal', '<=', self.date_to))
        if self.category_id:
            domain.append(('category_id', '=', self.category_id.id))
        if self.unit_name:
            domain.append(('unit_name', 'ilike', self.unit_name))

        tree_view = self.env.ref('pendapatan.view_pendapatan_list', raise_if_not_found=False)

        title_parts = []
        if self.category_id:
            title_parts.append(self.category_id.display_name)
        if self.date_from and self.date_to:
            title_parts.append(
                f"{self.date_from.strftime('%d/%m/%Y')} s/d {self.date_to.strftime('%d/%m/%Y')}"
            )
        elif self.date_from:
            title_parts.append(f"Mulai {self.date_from.strftime('%d/%m/%Y')}")
        elif self.date_to:
            title_parts.append(f"Sampai {self.date_to.strftime('%d/%m/%Y')}")

        window_title = "Laporan Pendapatan: " + " - ".join(title_parts) \
            if title_parts else "Laporan Pendapatan"

        return {
            'name': _(window_title),
            'type': 'ir.actions.act_window',
            'res_model': 'pendapatan.pendapatan',
            'view_mode': 'list',
            'domain': domain,
            'views': [(tree_view.id, 'list')] if tree_view else False,
            'target': 'current',
            'context': {
                'search_default_group_category': self.group_by == 'category',
                'search_default_group_unit': self.group_by == 'unit',
                'search_default_group_date_month': self.group_by == 'date_month',
            },
        }
