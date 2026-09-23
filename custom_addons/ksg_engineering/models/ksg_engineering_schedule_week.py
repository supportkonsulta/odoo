"""Kalender Minggu per Project (FR-011)."""

from odoo import models, fields, api


class KsgEngineeringScheduleWeek(models.Model):
    _name = 'ksg.engineering.schedule.week'
    _description = 'Kalender Minggu Engineering'
    _order = 'project_id, no_minggu'

    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='cascade', index=True)
    no_minggu = fields.Integer(string='Minggu Ke-', required=True)
    tanggal_mulai = fields.Date(string='Tanggal Mulai', required=True)
    tanggal_selesai = fields.Date(string='Tanggal Selesai', required=True)

    _unique_project_week = models.Constraint(
        'UNIQUE(project_id, no_minggu)',
        'Nomor minggu harus unik per project.',
    )

    @api.depends('no_minggu', 'tanggal_mulai', 'tanggal_selesai')
    def _compute_display_name(self):
        for rec in self:
            if rec.tanggal_mulai and rec.tanggal_selesai:
                rec.display_name = f"Minggu {rec.no_minggu} ({rec.tanggal_mulai.strftime('%d %b %y')} - {rec.tanggal_selesai.strftime('%d %b %y')})"
            else:
                rec.display_name = f"Minggu {rec.no_minggu}"
