# PLACEHOLDER: modul ini akan dikembangkan oleh tim Billing.
# Saat ini hanya sebagai konsumen downstream untuk verifikasi integrasi Engineering.

from odoo import models, fields


class KsgBillingInvoice(models.Model):
    _name = 'ksg.billing.invoice'
    _description = 'KSG Billing Invoice (Placeholder)'
    _inherit = ['mail.thread']

    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='restrict', tracking=True)
    bapbast_approved = fields.Boolean(
        related='project_id.bapbast_approved', string='BAP/BAST Disetujui',
        store=True, readonly=True)
