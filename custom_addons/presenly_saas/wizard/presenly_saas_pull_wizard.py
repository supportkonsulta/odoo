import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MONTHS = [
    ('1', 'Januari'), ('2', 'Februari'), ('3', 'Maret'), ('4', 'April'),
    ('5', 'Mei'), ('6', 'Juni'), ('7', 'Juli'), ('8', 'Agustus'),
    ('9', 'September'), ('10', 'Oktober'), ('11', 'November'), ('12', 'Desember'),
]


class PresenlySaasPullWizard(models.TransientModel):
    """Pilih periode sebelum menarik log dan rekap presensi.

    Periodenya dipilih eksplisit, bukan diam-diam memakai bulan berjalan,
    supaya tidak ada yang mengira sudah menarik bulan tertentu padahal belum.
    """

    _name = 'presenly.saas.pull.wizard'
    _description = 'Presenly SaaS Pull Attendance'

    config_id = fields.Many2one(
        'presenly.saas.config', required=True, ondelete='cascade',
    )
    month = fields.Selection(MONTHS, required=True)
    year = fields.Integer(required=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        values.setdefault('month', str(today.month))
        values.setdefault('year', today.year)
        if not values.get('config_id'):
            values['config_id'] = self.env['presenly.saas.config']._get_or_create().id
        return values

    def action_pull(self):
        self.ensure_one()
        self.config_id._ensure_manager()

        summary, error = self.config_id._pull_attendance(int(self.month), int(self.year))
        if error:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'title': _('Gagal menarik data presensi'),
                    'message': error,
                    'sticky': True,
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }

        message = _("Log presensi: %(logs)s baris. Rekap: %(recap)s baris.",
                    logs=summary['logs'], recap=summary['recap'])
        if summary['truncated']:
            # Diberitahukan, bukan disembunyikan: cermin yang terpotong harus
            # terlihat sebagai terpotong.
            message = '%s\n%s' % (message, '\n'.join(summary['truncated']))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning' if summary['truncated'] else 'success',
                'title': _('Penarikan selesai untuk %s', summary['period']),
                'message': message,
                'sticky': bool(summary['truncated']),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
