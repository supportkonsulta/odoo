# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class Pendapatan(models.Model):
    _name = 'pendapatan.pendapatan'
    _description = 'Pencatatan Pendapatan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tanggal desc, id desc'

    # ------------------------------------------------------------------
    # HEADER FIELDS
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Nomor Pendapatan',
        required=True,
        copy=False,
        readonly=True,
        default='New'
    )
    tanggal = fields.Date(
        string='Tanggal Pendapatan',
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )

    period_label = fields.Char(
        string='Label Periode',
        required=True,
        help='Contoh: "Januari 2026", "Semester Genap 2025/2026", "TA 2026/2027"',
        tracking=True
    )

    # ------------------------------------------------------------------
    # KATEGORI
    # ------------------------------------------------------------------
    category_id = fields.Many2one(
        'pendapatan.category',
        string='Kategori Pendapatan',
        required=True,
        ondelete='restrict',
        tracking=True
    )

    # ------------------------------------------------------------------
    # NOMINAL & SUMBER
    # ------------------------------------------------------------------
    amount = fields.Monetary(
        string='Nominal Pendapatan',
        required=True,
        currency_field='currency_id',
        tracking=True
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Mata Uang',
        required=True,
        default=lambda self: self.env.company.currency_id
    )

    unit_name = fields.Char(
        string='Unit Kerja / Sekolah',
        default='KANTOR',
        help='Misal: Sekolah ABC, Universitas XYZ, dll.'
    )

    source_partner_id = fields.Many2one(
        'res.partner',
        string='Pemberi Pendapatan (Opsional)',
        help='Misal: nama siswa / customer (jika diperlukan)'
    )

    description = fields.Text(
        string='Keterangan / Uraian'
    )

    attachment = fields.Binary(
        string='Bukti / Kwitansi',
        attachment=True
    )

    # ------------------------------------------------------------------
    # STATE MACHINE
    # ------------------------------------------------------------------
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Diajukan'),
        ('approved', 'Disetujui'),
        ('posted', 'Diposting'),
        ('cancelled', 'Dibatalkan'),
    ], string='Status', default='draft', required=True, tracking=True)

    submitted_by_id = fields.Many2one(
        'res.users',
        string='Diajukan Oleh',
        readonly=True
    )
    submitted_date = fields.Datetime(
        string='Tanggal Diajukan',
        readonly=True
    )

    approved_by_id = fields.Many2one(
        'res.users',
        string='Disetujui Oleh',
        readonly=True,
        tracking=True
    )
    approved_date = fields.Datetime(
        string='Tanggal Disetujui',
        readonly=True
    )

    posted_by_id = fields.Many2one(
        'res.users',
        string='Diposting Oleh',
        readonly=True
    )
    posted_date = fields.Datetime(
        string='Tanggal Diposting',
        readonly=True
    )

    cancel_reason = fields.Text(
        string='Alasan Pembatalan'
    )

    # ------------------------------------------------------------------
    # INTEGRASI JURNAL
    # ------------------------------------------------------------------
    journal_id = fields.Many2one(
        'sif.jurnal.entry',
        string='Jurnal Besar',
        readonly=True,
        copy=False,
        ondelete='restrict'
    )

    # ------------------------------------------------------------------
    # COMPANY
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company',
        string='Perusahaan',
        required=True,
        default=lambda self: self.env.company
    )

    # ------------------------------------------------------------------
    # SQL CONSTRAINTS
    # ------------------------------------------------------------------
    _sql_constraints = [
        ('amount_positive', 'CHECK(amount > 0)',
         'Nominal pendapatan harus lebih besar dari 0!'),
    ]

    # ------------------------------------------------------------------
    # CREATE - SEQUENCE
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'pendapatan.pendapatan'
                ) or 'New'
        return super(Pendapatan, self).create(vals_list)

    # ------------------------------------------------------------------
    # STATE TRANSITIONS - WORKFLOW
    # ------------------------------------------------------------------
    def action_submit(self):
        """Draft → Submitted (oleh user biasa)"""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Hanya pendapatan berstatus Draft yang dapat diajukan.'))
            if rec.amount <= 0:
                raise UserError(_('Nominal pendapatan harus lebih besar dari 0.'))
            if not rec.category_id.coa_pendapatan_id:
                raise UserError(_('Kategori "%s" belum memiliki Akun Pendapatan (COA).') % rec.category_id.name)
            if not rec.category_id.coa_kas_id:
                raise UserError(_('Kategori "%s" belum memiliki Akun Kas/Bank Penerima.') % rec.category_id.name)

            rec.write({
                'state': 'submitted',
                'submitted_by_id': self.env.user.id,
                'submitted_date': fields.Datetime.now(),
            })
        return True

    def action_approve(self):
        """Submitted → Approved (oleh manager)"""
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Hanya pendapatan berstatus Diajukan yang dapat disetujui.'))

            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            })
        return True

    def action_reject(self):
        """Submitted → Draft (tolak, kembali ke draft untuk revisi)"""
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Hanya pendapatan berstatus Diajukan yang dapat ditolak.'))
            rec.write({
                'state': 'draft',
                'submitted_by_id': False,
                'submitted_date': False,
            })
        return True

    def action_post(self):
        """Approved → Posted + auto-create Jurnal di sif.jurnal.entry"""
        JurnalEntry = self.env['sif.jurnal.entry']
        JurnalLine = self.env['sif.jurnal.line']

        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Hanya pendapatan berstatus Disetujui yang dapat diposting.'))
            if rec.journal_id:
                raise UserError(_('Pendapatan ini sudah memiliki jurnal terkait.'))
            if not rec.category_id.coa_pendapatan_id or not rec.category_id.coa_kas_id:
                raise UserError(_('Akun COA Pendapatan dan Kas/Bank pada kategori harus terisi untuk posting.'))

            coa_kas = rec.category_id.coa_kas_id
            coa_pendapatan = rec.category_id.coa_pendapatan_id

            lines = [
                (0, 0, {
                    'account_id': coa_kas.id,
                    'name': _('Pendapatan %s - %s') % (rec.name, rec.period_label or ''),
                    'debit': rec.amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': coa_pendapatan.id,
                    'name': _('Pendapatan %s - %s') % (rec.name, rec.period_label or ''),
                    'debit': 0.0,
                    'credit': rec.amount,
                }),
            ]

            entry_vals = {
                'date': rec.tanggal,
                'ref': rec.name,
                'kwitansi_ref': rec.name,
                'unit_name': rec.unit_name or 'KANTOR',
                'source_type': 'pendapatan',
                'line_ids': lines,
            }

            entry = JurnalEntry.sudo().create(entry_vals)
            entry.action_post()

            rec.write({
                'state': 'posted',
                'journal_id': entry.id,
                'posted_by_id': self.env.user.id,
                'posted_date': fields.Datetime.now(),
            })

        return True

    def action_cancel(self):
        """Batalkan pendapatan (hanya dari submitted/approved/posted)"""
        for rec in self:
            if rec.state in ('draft', 'cancelled'):
                raise UserError(_('Pendapatan sudah dalam status Draft / Dibatalkan.'))
            if rec.state == 'posted' and rec.journal_id:
                raise UserError(_(
                    'Pendapatan ini sudah terposting dan memiliki jurnal di Buku Besar.\n'
                    'Batalkan jurnal tersebut lebih dulu di modul Jurnal Besar.'
                ))

            rec.write({
                'state': 'cancelled',
                'cancel_reason': rec.cancel_reason or 'Dibatalkan oleh %s' % self.env.user.name,
            })
        return True

    def action_reset_to_draft(self):
        """Kembalikan ke draft (untuk koreksi, hanya manager)"""
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_('Pendapatan yang sudah terposting tidak dapat dikembalikan ke draft.'))
            rec.write({
                'state': 'draft',
                'submitted_by_id': False,
                'submitted_date': False,
                'approved_by_id': False,
                'approved_date': False,
                'cancel_reason': False,
            })
        return True

    # ------------------------------------------------------------------
    # RPC HOOK UNTUK INTEGRASI MODUL LAIN
    # ------------------------------------------------------------------
    @api.model
    def create_pendapatan_from_external(self, vals):
        """
        RPC helper untuk membuat pendapatan dari modul lain.
        Akan langsung mengajukan (action_submit) & auto-approve & post.
        """
        rec = self.sudo().create(vals)
        rec.action_submit()
        rec.action_approve()
        rec.action_post()
        return rec
