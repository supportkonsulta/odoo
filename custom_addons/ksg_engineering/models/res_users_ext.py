"""Extend res.users dengan assigned_project_ids (FR-012A)."""

from odoo import models, fields, api


class ResUsersExt(models.Model):
    _inherit = 'res.users'

    assigned_project_ids = fields.Many2many(
        'ksg.sales.project', string='Project yang Di-assign',
        compute='_compute_assigned_projects',
        help='Project yang saat ini di-assign ke user ini via Engineering.')

    def _compute_assigned_projects(self):
        """Search ksg.engineering.assignment yang aktif untuk user ini."""
        Assignment = self.env['ksg.engineering.assignment']
        for user in self:
            assignments = Assignment.search([
                ('user_id', '=', user.id),
                ('active', '=', True),
            ])
            user.assigned_project_ids = assignments.mapped('project_id')
