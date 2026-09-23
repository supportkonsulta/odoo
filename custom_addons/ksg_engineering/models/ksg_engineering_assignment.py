"""Assignment personel ke Project (FR-012)."""

from odoo import models, fields


class KsgEngineeringAssignment(models.Model):
    _name = 'ksg.engineering.assignment'
    _description = 'Assignment Engineering'
    _inherit = ['mail.thread']
    _order = 'project_id, peran'

    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='cascade', index=True, tracking=True)
    user_id = fields.Many2one(
        'res.users', string='Personel', required=True,
        index=True, tracking=True)
    peran = fields.Selection([
        ('pelaksana', 'Pelaksana'),
        ('engineer', 'Engineer'),
        ('design_engineer', 'Design Engineer'),
        ('pengawas', 'Pengawas'),
        ('supervisor', 'Supervisor'),
        ('kepala_unit', 'Kepala Unit'),
    ], string='Peran', required=True, tracking=True)
    tanggal_mulai_tugas = fields.Date(
        string='Tanggal Mulai Tugas', tracking=True)
    tanggal_selesai_tugas = fields.Date(
        string='Tanggal Selesai Tugas', tracking=True)
    active = fields.Boolean(string='Aktif', default=True)
