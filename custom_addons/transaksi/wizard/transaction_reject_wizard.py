# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TransaksiRejectWizard(models.TransientModel):
    _name = "transaksi.reject.wizard"
    _description = "Wizard Penolakan Transaksi"

    transaction_id = fields.Many2one(
        "transaksi.transaction",
        string="Dokumen Transaksi",
        required=True,
    )
    reason = fields.Text(
        string="Alasan Penolakan",
        required=True,
    )

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise ValidationError(_("Alasan penolakan wajib diisi."))
        return self.transaction_id.action_reject(reason=self.reason.strip())
