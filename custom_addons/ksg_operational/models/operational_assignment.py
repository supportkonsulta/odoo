from odoo import models, fields, api

class KsgSalesWorker(models.Model):
    _name = 'ksg.sales.worker'
    _description = 'Master Data Tenaga Kerja'

    name = fields.Char(string='Nama Pekerja', required=True)
    nik = fields.Char(string='NIK')
    posisi = fields.Char(string='Posisi / Jabatan')


class KsgOperationalAssignment(models.Model):
    _name = 'ksg.operational.assignment'
    _description = 'Penugasan Tenaga Kerja ke Proyek (Dikelola Eksklusif oleh HC)'
    _inherit = ['mail.thread']

    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    worker_id = fields.Many2one('ksg.sales.worker', string='Tenaga Kerja', required=True, tracking=True)
    tanggal_mulai_tugas = fields.Date(string='Tanggal Mulai', required=True, default=fields.Date.today)
    tanggal_selesai_tugas = fields.Date(string='Tanggal Selesai')
    status_aktif = fields.Boolean(string='Status Aktif', compute='_compute_status_aktif', store=True)

    @api.depends('tanggal_selesai_tugas')
    def _compute_status_aktif(self):
        today = fields.Date.today()
        for rec in self:
            if rec.tanggal_selesai_tugas and rec.tanggal_selesai_tugas <= today:
                rec.status_aktif = False
            else:
                rec.status_aktif = True

    @api.model
    def cron_update_worker_active_status(self):
        assignments = self.search([])
        assignments._compute_status_aktif()
