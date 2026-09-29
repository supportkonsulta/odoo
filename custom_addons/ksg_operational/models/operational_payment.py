from odoo import models, fields, api, _

class KsgOperationalPaymentRequest(models.Model):
    _name = 'ksg.operational.payment.request'
    _description = 'Pengajuan Dana & Pembayaran Operasional'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tanggal_pengajuan desc, id desc'

    name = fields.Char(string='Nomor Pengajuan', required=True, copy=False, default=lambda self: _('Draft Pengajuan'))
    project_id = fields.Many2one('ksg.sales.project', string='Proyek Terkait', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)
    tanggal_pengajuan = fields.Date(string='Tanggal Pengajuan', default=fields.Date.context_today, tracking=True)
    requested_by = fields.Many2one('res.users', string='Diajukan Oleh', default=lambda self: self.env.user, tracking=True)

    keperluan = fields.Text(string='Keperluan / Deskripsi Pengadaan', required=True)
    kategori_dana = fields.Selection([
        ('pengadaan', 'Pengadaan Barang & Alat Lapangan'),
        ('chemical', 'Bahan Kimia / Chemical'),
        ('subkon', 'Jasa Subkontraktor / Servis'),
        ('operasional', 'Biaya Operasional / Kas Lapangan'),
        ('lainnya', 'Lain-lain')
    ], string='Kategori Dana', default='pengadaan', required=True)

    nominal_pengajuan = fields.Monetary(string='Nominal Pengajuan (Rp)', required=True, currency_field='currency_id', tracking=True)

    # Info Rekening Pembayaran
    bank_tujuan = fields.Char(string='Bank Penerima', placeholder='Contoh: BCA / Mandiri / BRI', required=True)
    nomor_rekening = fields.Char(string='Nomor Rekening', required=True)
    atas_nama_rekening = fields.Char(string='Atas Nama Rekening', required=True)

    # Berkas Pengajuan Pra-Pembayaran (Bisa langsung diunggah saat Draft)
    file_nota = fields.Binary(string='Nota / Kwitansi / Invoice Pembelian')
    filename_nota = fields.Char(string='Nama File Nota')
    file_penawaran = fields.Binary(string='Surat Penawaran Vendor')
    filename_penawaran = fields.Char(string='Nama File Penawaran')
    file_brosur = fields.Binary(string='Brosur / Spesifikasi Teknis')
    filename_brosur = fields.Char(string='Nama File Brosur')

    # Dokumen Tambahan Bebas Custom Nama (Bisa diisi saat Draft maupun seterusnya)
    document_ids = fields.One2many('ksg.operational.payment.document', 'payment_id', string='Dokumen Tambahan / Lain-lain')

    # Data Pencairan oleh Keuangan
    tanggal_bayar = fields.Date(string='Tanggal Pembayaran')
    file_bukti_transfer = fields.Binary(string='Bukti Transfer Keuangan')
    filename_transfer = fields.Char(string='Nama File Bukti Bayar')

    # Data PJK (Setelah Barang Diterima di Lapangan)
    file_bast = fields.Binary(string='BAST / Surat Jalan / Tanda Terima Barang')
    filename_bast = fields.Char(string='Nama File BAST')
    catatan_pjk = fields.Text(string='Catatan Realisasi PJK')
    state_pjk = fields.Selection([
        ('draft', 'Belum Ada PJK'),
        ('submitted', 'PJK Diserahkan'),
        ('verified', 'PJK Terverifikasi Keuangan')
    ], string='Status PJK', default='draft', tracking=True)

    alasan_penolakan = fields.Text(string='Alasan Penolakan', tracking=True)

    state = fields.Selection([
        ('draft', 'Draft (Operasional)'),
        ('waiting_keuangan', 'Menunggu Review Keuangan'),
        ('waiting_direktur', 'Menunggu Approval Direktur'),
        ('approved', 'Disetujui (Siap Dibayar Keuangan)'),
        ('paid', 'Sudah Ditransfer (Menunggu PJK)'),
        ('done', 'Selesai (PJK Valid)'),
        ('rejected', 'Ditolak')
    ], string='Status Pengajuan', default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Draft Pengajuan')) in [_('Draft Pengajuan'), 'Draft Pengajuan', False]:
                vals['name'] = self.env['ir.sequence'].next_by_code('ksg.operational.payment') or _('Draft Pengajuan')
        return super().create(vals_list)

    def action_submit(self):
        self.write({'state': 'waiting_keuangan', 'alasan_penolakan': False})

    def action_keuangan_approve(self):
        self.write({'state': 'waiting_direktur'})

    def action_direktur_approve(self):
        self.write({'state': 'approved'})

    def action_pay(self):
        self.ensure_one()
        self.write({
            'state': 'paid',
            'tanggal_bayar': fields.Date.context_today(self) if not self.tanggal_bayar else self.tanggal_bayar
        })

    def action_submit_pjk(self):
        self.ensure_one()
        self.write({'state_pjk': 'submitted'})

    def action_verify_pjk(self):
        self.ensure_one()
        self.write({'state_pjk': 'verified', 'state': 'done'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_reject_wizard(self):
        self.ensure_one()
        return {
            'name': _('Tolak Pengajuan Dana'),
            'type': 'ir.actions.act_window',
            'res_model': 'ksg.operational.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            }
        }


class KsgOperationalPaymentDocument(models.Model):
    _name = 'ksg.operational.payment.document'
    _description = 'Dokumen Tambahan / Pendukung PJK Operasional'

    payment_id = fields.Many2one('ksg.operational.payment.request', string='Pengajuan Dana', ondelete='cascade')
    name = fields.Char(string='Nama / Jenis Dokumen', required=True, placeholder='Contoh: Foto Barang Tiba, Tiket Tol, Kartu Garansi, Kuitansi DP')
    file = fields.Binary(string='File Dokumen', required=True)
    filename = fields.Char(string='Nama File')
    keterangan = fields.Char(string='Keterangan Tambahan')