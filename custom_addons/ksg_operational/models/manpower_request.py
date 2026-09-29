from odoo import models, fields, api, _

class KsgOperationalManpowerRequest(models.Model):
    _name = 'ksg.operational.manpower.request'
    _description = 'Permintaan Tenaga Kerja Lapangan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tanggal_pengajuan desc, id desc'

    name = fields.Char(string='Nomor Permintaan SDM', required=True, copy=False, default=lambda self: _('Draft SDM'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek Terkait', required=True, tracking=True)
    tanggal_pengajuan = fields.Date(string='Tanggal Pengajuan', default=fields.Date.context_today)
    kebutuhan_waktu = fields.Char(string='Kebutuhan Durasi Lapangan', placeholder='Contoh: 12 Bulan / Mulai 1 Oktober 2026')

    line_ids = fields.One2many('ksg.operational.manpower.request.line', 'request_id', string='Rincian Kebutuhan SDM')
    total_tenaga_kerja = fields.Integer(string='Total Kebutuhan Personil', compute='_compute_total_tenaga_kerja', store=True)

    catatan = fields.Text(string='Catatan Operasional untuk Tim HC')
    alasan_penolakan = fields.Text(string='Alasan Penolakan', tracking=True)

    state = fields.Selection([
        ('draft', 'Draft (Operasional)'),
        ('submitted', 'Diajukan ke HC'),
        ('approved', 'Disetujui / Terpenuhi'),
        ('rejected', 'Ditolak')
    ], string='Status', default='draft', tracking=True)

    @api.depends('line_ids.jumlah')
    def _compute_total_tenaga_kerja(self):
        for rec in self:
            rec.total_tenaga_kerja = sum(rec.line_ids.mapped('jumlah'))

    def action_submit(self):
        self.write({'state': 'submitted', 'alasan_penolakan': False})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_reject_wizard(self):
        self.ensure_one()
        return {
            'name': _('Tolak Permintaan SDM'),
            'type': 'ir.actions.act_window',
            'res_model': 'ksg.operational.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Draft SDM')) in [_('Draft SDM'), 'Draft SDM', False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.manpower') or _('Draft SDM')
        return super().create(vals_list)


class KsgOperationalManpowerRequestLine(models.Model):
    _name = 'ksg.operational.manpower.request.line'
    _description = 'Item Permintaan Tenaga Kerja'

    request_id = fields.Many2one('ksg.operational.manpower.request', string='Dokumen SDM', ondelete='cascade')
    jabatan = fields.Char(string='Posisi / Jabatan yang Dibutuhkan', required=True, placeholder='Contoh: Cleaning Service, Team Leader, Teknisi ME, Gardener')
    jumlah = fields.Integer(string='Jumlah (Orang)', required=True, default=1)
    kualifikasi_khusus = fields.Char(string='Kualifikasi / Keterangan Khusus', placeholder='Contoh: Pria, maks 35 th, punya sertifikat K3')