import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SKIP_CONTEXT_KEY = 'presenly_saas_skip_guard'


class PresenlySaasGuard(models.AbstractModel):
    """Policy API for other modules.

    This module never touches a native business model, so nothing is blocked
    automatically. A module that wants to enforce the subscription calls this
    API at its own decision point::

        self.env['presenly.saas.guard'].check('attendance.check_in')

    Pass ``presenly_saas_skip_guard=True`` in the context to let system
    operations (imports, migrations, internal crons) through.
    """

    _name = 'presenly.saas.guard'
    _description = 'Presenly SaaS Guard'

    # ------------------------------------------------------------------
    # Read-only state
    # ------------------------------------------------------------------
    @api.model
    def _subscription_snapshot(self):
        """Snapshot langganan company aktif, atau recordset kosong."""
        config = self.env['presenly.saas.config'].sudo()._get_or_create()
        return self.env['presenly.saas.subscription'].sudo().search(
            [('company_id', '=', config.company_id.id)], limit=1
        )

    @api.model
    def state(self):
        """Ringkasan keadaan langganan untuk company aktif."""
        config = self.env['presenly.saas.config'].sudo()._get_or_create()
        subscription = self._subscription_snapshot()

        if not subscription:
            return {
                'enabled': config.enabled,
                'guard_mode': config.guard_mode,
                'status': 'unknown',
                'state_source': 'unreachable',
                'effective_state': 'allowed',
                'has_snapshot': False,
                'days_remaining': 0,
                'seat_limit': 0,
                'seats_used': 0,
                'grace_until': False,
                'plan_name': False,
                'missing_features': [],
            }

        return {
            'enabled': config.enabled,
            'guard_mode': config.guard_mode,
            'status': subscription.status,
            'state_source': subscription.state_source,
            'effective_state': subscription._effective_state(),
            'has_snapshot': True,
            'days_remaining': subscription.days_remaining,
            'seat_limit': subscription.seat_limit,
            'seats_used': subscription.seats_used,
            'grace_until': subscription.grace_until,
            'plan_name': subscription.plan_name,
            'missing_features': sorted(subscription._missing_feature_codes()),
        }

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------
    @api.model
    def is_allowed(self, operation=None):
        """Return True when ``operation`` may proceed.

        ``operation`` is only used for logging and for the error message. The
        decision itself is per company, not per operation.
        """
        if self.env.context.get(SKIP_CONTEXT_KEY):
            return True
        return self.state()['effective_state'] == 'allowed'

    @api.model
    def check(self, operation=None):
        """Raise a UserError when the subscription blocks ``operation``."""
        if self.is_allowed(operation):
            return True

        state = self.state()
        message = _(
            "Presenly SaaS subscription is not active (status: %(status)s). "
            "Renew the subscription, or ask a Presenly SaaS manager to review "
            "the connection settings.",
            status=state['status'],
        )
        if operation:
            _logger.info("Presenly SaaS guard blocked %s", operation)
        raise UserError(message)

    @api.model
    def has_feature(self, code=None):
        """Apakah paket tenant ini mencakup fitur `code`.

        Aturan yang dipegang sama dengan sisi SaaS, dan sengaja konservatif:

        - Tanpa kode, atau tanpa snapshot, atau snapshot tanpa daftar fitur:
          **True**. Tidak ada data bukan alasan untuk mencabut akses. Ini juga
          yang membuat instalasi lama tetap berjalan, karena field `plan_features`
          baru terisi setelah penyegaran pertama.
        - Paket yang tidak terdaftar di sisi SaaS juga dikirim dengan seluruh
          fitur terbuka, jadi tidak ada kejadian "paket salah tulis lalu akses
          hilang" tanpa keputusan eksplisit seseorang.

        Karena itu, `False` hanya keluar bila server benar-benar mengirim
        `included: false` untuk kode tersebut.
        """
        if not code:
            return True

        subscription = self._subscription_snapshot()
        if not subscription or not subscription.plan_features:
            return True

        # Hanya `included: false` yang eksplisit yang mencabut akses. Kode yang
        # tidak disebut server dapat berarti katalog di sisi SaaS lebih tua
        # daripada modul ini, dan itu bukan alasan untuk memblokir.
        return code not in subscription._missing_feature_codes()

    @api.model
    def missing_features(self):
        """Kode fitur yang tidak termasuk pada paket tenant ini."""
        subscription = self._subscription_snapshot()
        if not subscription:
            return []
        return sorted(subscription._missing_feature_codes())
