import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MONTHS = [
    ('1', 'January'), ('2', 'February'), ('3', 'March'), ('4', 'April'),
    ('5', 'May'), ('6', 'June'), ('7', 'July'), ('8', 'August'),
    ('9', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December'),
]


class PresenlySaasPullWizard(models.TransientModel):
    """Pilih periode sebelum menarik data Presenly.

    Satu periode berisi presensi (log dan rekap) serta lima jenis pengajuan:
    cuti, lembur, surat dokter, koreksi presensi, dan tukar shift.

    Periodenya dipilih eksplisit, bukan diam-diam memakai bulan berjalan,
    supaya tidak ada yang mengira sudah menarik bulan tertentu padahal belum.
    """

    _name = 'presenly.saas.pull.wizard'
    _description = 'Presenly SaaS Pull Period'

    config_id = fields.Many2one(
        'presenly.saas.config', required=True, ondelete='cascade',
    )
    month = fields.Selection(MONTHS, required=True, string='End Month')
    year = fields.Integer(required=True, string='End Year')
    months_back = fields.Integer(
        string='How Many Months Back',
        default=1,
        required=True,
        help='1 means only the selected month. 3 means that month and the two '
             'before it, to fill the monitoring mirror.',
    )

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

        if self.months_back < 1:
            raise UserError(_("The number of months must be at least 1."))

        summary, error = self.config_id._pull_period_range(
            int(self.month), int(self.year), self.months_back
        )
        if error:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'title': _('Failed to pull period data'),
                    'message': error,
                    'sticky': True,
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }

        dataset_total = sum(summary['datasets'].values())
        message = _(
            "%(months)s months: %(logs)s attendance log rows, "
            "%(datasets)s requests and timesheet rows.",
            months=summary['months'], logs=summary['logs'],
            datasets=dataset_total,
        )

        # Diberitahukan, bukan disembunyikan: cermin yang terpotong harus
        # terlihat sebagai terpotong.
        notices = list(summary['truncated'])

        # Rentang yang lebih tua dari jendela bergulir akan ditarik sekarang,
        # lalu dihapus lagi oleh pembersihan mingguan. Mengatakannya di sini
        # lebih berguna daripada membiarkan data itu terlihat hilang tanpa sebab.
        cutoff = self.config_id._retention_cutoff()
        if cutoff:
            earliest = date(int(self.year), int(self.month), 1) - relativedelta(
                months=int(self.months_back) - 1
            )
            if earliest < cutoff.replace(day=1):
                notices.append(_(
                    "Part of this range is older than the retention window "
                    "(%(months)s months). The weekly cleanup will remove it "
                    "again; raise Retention in Settings to keep it.",
                    months=self.config_id.retention_months,
                ))
        if notices:
            message = '%s\n\n%s' % (message, '\n'.join(notices))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning' if notices else 'success',
                'title': _('Pull finished: %s', ', '.join(summary['periods'])),
                'message': message,
                'sticky': bool(notices),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
