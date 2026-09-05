from odoo import models, fields, api
from odoo.exceptions import ValidationError

class SifJurnalEntry(models.Model):
    _name = 'sif.jurnal.entry'
    _description = 'Input Jurnal Transaksi Keuangan'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nomor Referensi', required=True, copy=False, readonly=True, default='Baru')
    date = fields.Date(string='Tanggal Jurnal', required=True, default=fields.Date.context_today)
    reference = fields.Char(string='Keterangan / Memo', required=True)
    source_document = fields.Char(string='Dokumen Sumber / No. PPL', readonly=True)
    
    unit_dept = fields.Selection([
        ('tpa', 'TPA'),
        ('sd', 'SD'),
        ('smp', 'SMP'),
        ('sma', 'SMA'),
        ('univ', 'Universitas'),
        ('pusat', 'Yayasan / Kantor Pusat'),
    ], string='Unit / Departemen', required=True, default='pusat')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Tervalidasi (Posted)'),
        ('cancel', 'Dibatalkan'),
    ], string='Status', default='draft', readonly=True)

    line_ids = fields.One2many('sif.jurnal.line', 'entry_id', string='Rincian Debit/Kredit')
    total_debit = fields.Float(string='Total Debit', compute='_compute_totals', store=True)
    total_credit = fields.Float(string='Total Kredit', compute='_compute_totals', store=True)

    @api.depends('line_ids.debit', 'line_ids.credit')
    def _compute_totals(self):
        for rec in self:
            rec.total_debit = sum(rec.line_ids.mapped('debit'))
            rec.total_credit = sum(rec.line_ids.mapped('credit'))

    def action_post(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError("Rincian jurnal kosong! Masukkan minimal dua akun.")
            if round(rec.total_debit, 2) != round(rec.total_credit, 2):
                raise ValidationError(
                    f"Jurnal tidak balance! Total Debit ({rec.total_debit:,.2f}) tidak sama dengan Total Kredit ({rec.total_credit:,.2f})."
                )
            if rec.name == 'Baru':
                seq = self.env['ir.sequence'].next_by_code('sif.jurnal.entry')
                rec.name = seq or f"JRN/{rec.date.strftime('%Y%m')}/{rec.id:04d}"
            rec.state = 'posted'

    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

    @api.model
    def create_journal_from_ppl(self, ppl_data):
        """Metode integrasi untuk otomatisasi pencatatan jurnal dari modul PPL"""
        entry = self.create({
            'date': ppl_data.get('date', fields.Date.context_today(self)),
            'reference': ppl_data.get('reference', 'Pembayaran PPL Otomatis'),
            'source_document': ppl_data.get('source_document', ''),
            'unit_dept': ppl_data.get('unit_dept', 'pusat'),
            'line_ids': [(0, 0, line) for line in ppl_data.get('lines', [])]
        })
        entry.action_post()
        return entry


class SifJurnalLine(models.Model):
    _name = 'sif.jurnal.line'
    _description = 'Buku Besar'
    _order = 'date desc, id desc'

    entry_id = fields.Many2one('sif.jurnal.entry', string='Jurnal Induk', ondelete='cascade', required=True)
    account_id = fields.Many2one('sif.coa', string='Akun Rekening', required=True)
    account_type = fields.Selection(related='account_id.account_type', string='Kategori Akun', store=True)
    name = fields.Char(string='Keterangan Baris')
    date = fields.Date(related='entry_id.date', string='Tanggal', store=True, index=True)
    unit_dept = fields.Selection(related='entry_id.unit_dept', string='Unit Kerja', store=True, index=True)
    state = fields.Selection(related='entry_id.state', string='Status', store=True)
    debit = fields.Float(string='Debit', default=0.0)
    credit = fields.Float(string='Kredit', default=0.0)
    
    # Helper fields untuk filter bulanan (DoD SRS 3.3.2)
    period_month = fields.Selection([
        ('01', 'Januari'),
        ('02', 'Februari'),
        ('03', 'Maret'),
        ('04', 'April'),
        ('05', 'Mei'),
        ('06', 'Juni'),
        ('07', 'Juli'),
        ('08', 'Agustus'),
        ('09', 'September'),
        ('10', 'Oktober'),
        ('11', 'November'),
        ('12', 'Desember'),
    ], string='Bulan', compute='_compute_period', store=True, index=True)
    period_year = fields.Char(string='Tahun', compute='_compute_period', store=True, index=True)
    period_key = fields.Char(string='Periode (YYYY-MM)', compute='_compute_period', store=True, index=True)
    
    balance = fields.Float(string='Saldo Mutasi', compute='_compute_balance', store=True)

    @api.depends('date')
    def _compute_period(self):
        for rec in self:
            if rec.date:
                rec.period_month = rec.date.strftime('%m')
                rec.period_year = rec.date.strftime('%Y')
                rec.period_key = rec.date.strftime('%Y-%m')
            else:
                rec.period_month = False
                rec.period_year = False
                rec.period_key = False

    @api.depends('debit', 'credit', 'account_id.account_type')
    def _compute_balance(self):
        for rec in self:
            # Saldo normal: Aset & Beban = Debit - Kredit, lainnya = Kredit - Debit
            if rec.account_id.account_type in ('asset', 'expense'):
                rec.balance = rec.debit - rec.credit
            else:
                rec.balance = rec.credit - rec.debit
