from odoo import models, fields, api, _
from odoo.exceptions import UserError

class KsgOperationalRejectWizard(models.TransientModel):
    _name = 'ksg.operational.reject.wizard'
    _description = 'Wizard Alasan Penolakan Dokumen'

    res_model = fields.Char(string='Model Terkait', required=True)
    res_id = fields.Integer(string='ID Record', required=True)
    alasan_penolakan = fields.Text(string='Alasan Penolakan / Catatan Perbaikan', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_("Dokumen tidak ditemukan."))
        
        vals = {'state': 'rejected'}
        if 'alasan_penolakan' in record._fields:
            vals['alasan_penolakan'] = self.alasan_penolakan
        record.write(vals)
        if hasattr(record, 'message_post'):
            record.message_post(body=f"<b>Dokumen Ditolak:</b><br/>{self.alasan_penolakan}")
        return {'type': 'ir.actions.act_window_close'}