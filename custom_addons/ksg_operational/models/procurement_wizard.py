from odoo import models, fields, _
from odoo.exceptions import UserError

class KsgOperationalProcurementRejectWizard(models.TransientModel):
    _name = 'ksg.operational.procurement.reject.wizard'
    _description = 'Wizard Penolakan BoQ'

    procurement_id = fields.Many2one('ksg.operational.procurement.request', string='Dokumen BoQ', required=True)
    alasan_penolakan = fields.Text(string='Alasan Penolakan', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.alasan_penolakan:
            raise UserError(_("Mohon tuliskan alasan penolakan dokumen BoQ."))
        self.procurement_id.write({
            'state': 'rejected',
            'catatan_penolakan': self.alasan_penolakan,
            'approver_id': self.env.user.id,
            'tanggal_approval': fields.Datetime.now()
        })
        self.procurement_id.message_post(body=_("Dokumen BoQ DITOLAK oleh Direktur dengan catatan: %s") % self.alasan_penolakan)