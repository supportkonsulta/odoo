from odoo import models, fields, api, _
from odoo.exceptions import UserError

class KsgOperationalProcurementRequest(models.Model):
    _name = 'ksg.operational.procurement.request'
    _description = 'Pengajuan Pengadaan Proyek & Bill of Quantity (BoQ)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tanggal_pengajuan desc, id desc'

    name = fields.Char(string='Nomor Dokumen BoQ', required=True, copy=False, default=lambda self: _('Draft BoQ'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek', required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)

    # Computed fields agar aman dipanggil di QWeb report
    project_code = fields.Char(string='Kode Proyek', compute='_compute_project_display_info')
    project_name = fields.Char(string='Nama Pekerjaan', compute='_compute_project_display_info')
    client_name = fields.Char(string='Nama Klien', compute='_compute_project_display_info')

    tanggal_pengajuan = fields.Date(string='Tanggal Pengajuan', default=fields.Date.context_today, tracking=True)
    requested_by = fields.Many2one('res.users', string='Diajukan Oleh (Operasional)', default=lambda self: self.env.user, readonly=True)
    approver_id = fields.Many2one('res.users', string='Disetujui Oleh (Direktur)', readonly=True, tracking=True)
    tanggal_approval = fields.Datetime(string='Waktu Otorisasi', readonly=True)

    boq_line_ids = fields.One2many('ksg.operational.boq.line', 'procurement_id', string='Rincian Item BoQ')
    total_estimasi_biaya = fields.Monetary(string='Total Estimasi Biaya BoQ', compute='_compute_total_biaya', store=True, currency_field='currency_id')

    catatan_pengadaan = fields.Text(string='Catatan / Keterangan Kebutuhan')
    catatan_penolakan = fields.Text(string='Alasan Penolakan Direktur', readonly=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft Penyusunan BoQ'),
        ('waiting_approval', 'Menunggu Persetujuan Direktur'),
        ('approved', 'Disetujui Direktur (Siap Pengadaan)'),
        ('rejected', 'Ditolak Direktur')
    ], string='Status Dokumen', default='draft', tracking=True)

    @api.depends('project_id')
    def _compute_project_display_info(self):
        for rec in self:
            p = rec.project_id
            if p:
                rec.project_code = getattr(p, 'kode_proyek', False) or getattr(p, 'code', False) or p.display_name or ''
                rec.project_name = getattr(p, 'nama_pekerjaan', False) or getattr(p, 'name', False) or getattr(p, 'nama_proyek', False) or p.display_name or ''
                partner = getattr(p, 'partner_id', False) or getattr(p, 'client_id', False)
                rec.client_name = partner.name if partner else ''
            else:
                rec.project_code = ''
                rec.project_name = ''
                rec.client_name = ''

    @api.depends('boq_line_ids.subtotal_estimasi')
    def _compute_total_biaya(self):
        for rec in self:
            rec.total_estimasi_biaya = sum(rec.boq_line_ids.mapped('subtotal_estimasi'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Draft BoQ')) in [_('Draft BoQ'), 'Draft BoQ', _('New'), False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.procurement') or _('Draft BoQ')
        return super().create(vals_list)

    def action_submit(self):
        self.ensure_one()
        if not self.boq_line_ids:
            raise UserError(_("Rincian item BoQ tidak boleh kosong. Masukkan minimal 1 barang/alat."))
        self.write({'state': 'waiting_approval'})
        self.message_post(body=_("Dokumen BoQ telah diajukan ke Direktur untuk mendapatkan persetujuan pengadaan."))

    def action_approve(self):
        self.ensure_one()
        self.write({
            'state': 'approved',
            'approver_id': self.env.user.id,
            'tanggal_approval': fields.Datetime.now()
        })
        self.message_post(body=_("Dokumen BoQ telah DISETUJUI oleh Direktur (%s).") % self.env.user.name)

    def action_reject(self):
        self.ensure_one()
        return {
            'name': _('Penolakan Dokumen BoQ'),
            'type': 'ir.actions.act_window',
            'res_model': 'ksg.operational.procurement.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_procurement_id': self.id}
        }

    def action_reset_draft(self):
        self.ensure_one()
        self.write({'state': 'draft'})


class KsgOperationalBoqLine(models.Model):
    _name = 'ksg.operational.boq.line'
    _description = 'Baris Item Bill of Quantity'

    procurement_id = fields.Many2one('ksg.operational.procurement.request', string='Dokumen BoQ', ondelete='cascade')
    currency_id = fields.Many2one(related='procurement_id.currency_id')

    kategori = fields.Selection([
        ('material', 'Material & Bahan Pokok'),
        ('alat', 'Peralatan & Mesin Kerja'),
        ('apd', 'Perlengkapan K3 / APD'),
        ('seragam', 'Seragam & Atribut Pekerja'),
        ('konsumsi', 'Logistik & Operasional Proyek'),
        ('lainnya', 'Lain-lain')
    ], string='Kategori Item', required=True, default='material')

    item = fields.Char(string='Uraian Barang / Item Pekerjaan', required=True)
    spesifikasi = fields.Char(string='Spesifikasi Teknis / Merk / Dimensi', required=True)
    jumlah = fields.Float(string='Volume / Qty', required=True, default=1.0)
    satuan = fields.Char(string='Satuan', required=True, default='Unit', help='Contoh: Unit, Pcs, Set, Batang, Zak, Roll, Hari')
    harga_estimasi_satuan = fields.Monetary(string='Estimasi Harga Satuan', currency_field='currency_id')
    subtotal_estimasi = fields.Monetary(string='Total Estimasi (Rp)', compute='_compute_subtotal', store=True, currency_field='currency_id')
    keterangan = fields.Char(string='Keterangan / Posisi Lapangan')

    @api.depends('jumlah', 'harga_estimasi_satuan')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal_estimasi = line.jumlah * line.harga_estimasi_satuan