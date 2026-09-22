import logging
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

STATUS_SELECTION = [
    ('trial', 'Trial'),
    ('active', 'Active'),
    ('expired', 'Expired'),
    ('suspended', 'Suspended'),
    ('unknown', 'Unknown'),
]

STATE_SOURCE_SELECTION = [
    ('live', 'Live'),
    ('cached', 'Cached'),
    ('unreachable', 'Unreachable'),
]

# A paid subscription is flagged this many days before the period ends.
RENEWAL_WARNING_DAYS = 7


def parse_datetime(value):
    """Convert an ISO-8601 string from the SaaS API into a naive UTC datetime."""
    if not value:
        return False
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            _logger.warning("Presenly SaaS: unparsable datetime %r", value)
            return False
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


class PresenlySaasSubscription(models.Model):
    """Local snapshot of the tenant subscription held on the SaaS side.

    The SaaS server is the source of truth. This record only mirrors the last
    successful response, so the backend keeps working, and keeps telling the
    truth about how old that answer is, when the SaaS server cannot be reached.
    """

    _name = 'presenly.saas.subscription'
    _description = 'Presenly SaaS Subscription'
    _rec_name = 'tenant_code'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    config_id = fields.Many2one(
        'presenly.saas.config',
        required=True,
        ondelete='cascade',
        index=True,
    )

    tenant_code = fields.Char()
    client_name = fields.Char()
    plan_type = fields.Char(string='Plan')
    status = fields.Selection(STATUS_SELECTION, default='unknown', required=True)
    is_trial = fields.Boolean()

    trial_ends_at = fields.Datetime()
    current_period_end = fields.Datetime()
    days_remaining = fields.Integer(compute='_compute_days_remaining')

    seat_limit = fields.Integer()
    seats_used = fields.Integer()
    seat_usage_percent = fields.Float(compute='_compute_seat_usage_percent')
    price_per_user = fields.Integer()

    # ----------------------------------------------------------------
    # Profil perusahaan, dari tabel `clients` di sisi SaaS
    # ----------------------------------------------------------------
    tenant_email = fields.Char()
    tenant_whatsapp = fields.Char()
    tenant_business_sector = fields.Char()
    tenant_reference = fields.Char()
    # Angka yang dinyatakan klien di profilnya, bukan jumlah akun terpakai.
    # Bandingkan dengan `seats_used` hanya dengan sadar keduanya berbeda.
    tenant_employee_count = fields.Integer()
    tenant_joined_at = fields.Datetime()

    # ----------------------------------------------------------------
    # Paket & fitur
    # ----------------------------------------------------------------
    plan_name = fields.Char(string='Plan Name')
    plan_registered = fields.Boolean(
        help='True when the plan code is registered in the SaaS-side plan catalog.',
    )
    # Daftar apa adanya dari server: [{code, label, group, included}].
    plan_features = fields.Json(string='Plan Features')

    feature_count = fields.Integer(compute='_compute_feature_summary')
    included_feature_count = fields.Integer(compute='_compute_feature_summary')
    included_feature_codes = fields.Char(compute='_compute_feature_summary')
    missing_feature_codes = fields.Char(compute='_compute_feature_summary')
    features_summary = fields.Text(compute='_compute_feature_summary', string='Features')

    schema_version = fields.Char()
    server_time = fields.Datetime()

    last_sync_at = fields.Datetime()
    state_source = fields.Selection(
        STATE_SOURCE_SELECTION,
        default='unreachable',
        required=True,
    )
    grace_until = fields.Datetime(compute='_compute_grace_until')

    _company_uniq = models.Constraint(
        'unique(company_id)',
        'Only one subscription snapshot is stored per company.',
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('is_trial', 'trial_ends_at', 'current_period_end')
    def _compute_days_remaining(self):
        now = fields.Datetime.now()
        for subscription in self:
            end = subscription._validity_end()
            subscription.days_remaining = max(0, (end - now).days) if end else 0

    @api.depends('seat_limit', 'seats_used')
    def _compute_seat_usage_percent(self):
        for subscription in self:
            if subscription.seat_limit:
                subscription.seat_usage_percent = (
                    subscription.seats_used / subscription.seat_limit * 100.0
                )
            else:
                subscription.seat_usage_percent = 0.0

    @api.depends('last_sync_at', 'config_id.grace_days')
    def _compute_grace_until(self):
        for subscription in self:
            if subscription.last_sync_at and subscription.config_id.grace_days:
                subscription.grace_until = subscription.last_sync_at + relativedelta(
                    days=subscription.config_id.grace_days
                )
            else:
                subscription.grace_until = False

    def _validity_end(self):
        """The datetime the current subscription stops being valid."""
        self.ensure_one()
        if self.is_trial:
            return self.trial_ends_at or self.current_period_end
        return self.current_period_end or self.trial_ends_at

    def _status_label(self):
        """The status label in the language of the current user."""
        self.ensure_one()
        labels = dict(self._fields['status']._description_selection(self.env))
        return labels.get(self.status, self.status)

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------
    @api.model
    def _sanitize_features(self, features):
        """Rapikan daftar fitur dari server sebelum disimpan.

        Server bisa mengirim bentuk yang tidak terduga. Yang tidak berbentuk
        daftar dict berisi `code` dibuang, supaya compute di bawah tidak perlu
        menebak dan `has_feature()` tidak pernah menerima sampah.
        """
        if not isinstance(features, list):
            return []
        cleaned = []
        for item in features:
            if not isinstance(item, dict):
                continue
            code = item.get('code')
            if not code or not isinstance(code, str):
                continue
            cleaned.append({
                'code': code,
                'label': item.get('label') or code,
                'group': item.get('group') or '',
                'included': bool(item.get('included')),
            })
        return cleaned

    @api.depends('plan_features')
    def _compute_feature_summary(self):
        for subscription in self:
            features = subscription.plan_features or []
            included = [f for f in features if f.get('included')]
            missing = [f for f in features if not f.get('included')]

            subscription.feature_count = len(features)
            subscription.included_feature_count = len(included)
            subscription.included_feature_codes = ', '.join(f['code'] for f in included)
            subscription.missing_feature_codes = ', '.join(f['code'] for f in missing)

            # Judul bagian ini ikut diterjemahkan; label fitur tidak, karena
            # katalognya milik server SaaS. Lihat catatan di README.
            blocks = []
            if included:
                blocks.append(
                    '%s:\n%s' % (
                        _('Included'),
                        '\n'.join('- %s' % f['label'] for f in included),
                    )
                )
            if missing:
                blocks.append(
                    '%s:\n%s' % (
                        _('Not included'),
                        '\n'.join('- %s' % f['label'] for f in missing),
                    )
                )
            subscription.features_summary = '\n\n'.join(blocks)

    def _included_feature_codes(self):
        """Kode fitur yang termasuk, sebagai himpunan."""
        self.ensure_one()
        return {f['code'] for f in (self.plan_features or []) if f.get('included')}

    def _missing_feature_codes(self):
        self.ensure_one()
        return {f['code'] for f in (self.plan_features or []) if not f.get('included')}

    @api.model
    def _sync_from_payload(self, config, data):
        """Write the payload from the SaaS server into the company snapshot."""
        subscription = self.sudo().search(
            [('company_id', '=', config.company_id.id)], limit=1
        )
        status = data.get('status')
        if status not in dict(STATUS_SELECTION):
            status = 'unknown'

        values = {
            'company_id': config.company_id.id,
            'config_id': config.id,
            'tenant_code': data.get('tenant_code') or config.tenant_code,
            'client_name': data.get('client_name') or '',
            'plan_type': data.get('plan_type') or '',
            'status': status,
            'is_trial': bool(data.get('is_trial')),
            'trial_ends_at': parse_datetime(data.get('trial_ends_at')),
            'current_period_end': parse_datetime(data.get('current_period_end')),
            'seat_limit': int(data.get('seat_limit') or 0),
            'seats_used': int(data.get('seats_used') or 0),
            'price_per_user': int(data.get('price_per_user') or 0),
            'tenant_email': data.get('tenant_email') or False,
            'tenant_whatsapp': data.get('tenant_whatsapp') or False,
            'tenant_business_sector': data.get('tenant_business_sector') or False,
            'tenant_reference': data.get('tenant_reference') or False,
            'tenant_employee_count': int(data.get('tenant_employee_count') or 0),
            'tenant_joined_at': parse_datetime(data.get('tenant_joined_at')),
            'plan_name': data.get('plan_name') or False,
            'plan_registered': bool(data.get('plan_registered')),
            'plan_features': self._sanitize_features(data.get('features')),
            'schema_version': data.get('schema_version') or '',
            'server_time': parse_datetime(data.get('server_time')),
            'last_sync_at': fields.Datetime.now(),
            'state_source': 'live',
        }
        if subscription:
            subscription.write(values)
        else:
            subscription = self.sudo().create(values)
        return subscription

    @api.model
    def _mark_unreachable(self, company):
        """Flag the snapshot as not freshly confirmed, without changing status.

        The subscription status itself is only ever set from a response the
        SaaS server actually sent. A failed pull therefore downgrades the
        confidence level, not the status.
        """
        subscription = self.sudo().search([('company_id', '=', company.id)], limit=1)
        if not subscription:
            return subscription
        subscription.state_source = (
            'cached' if subscription.last_sync_at else 'unreachable'
        )
        return subscription

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------
    def _effective_state(self):
        """Return ``allowed`` or ``blocked`` for this snapshot.

        Blocking requires a negative status that the SaaS server actually
        returned. An unreachable server never blocks: the cached status stands
        until a fresh answer arrives.
        """
        self.ensure_one()
        config = self.config_id
        if not config.enabled or config.guard_mode != 'enforce':
            return 'allowed'
        if self.state_source in ('cached', 'unreachable'):
            return 'allowed'
        if self.status in ('expired', 'suspended'):
            return 'blocked'
        if self.status == 'trial' and self.is_trial:
            end = self.trial_ends_at or self.current_period_end
            if end and fields.Datetime.now() > end:
                return 'blocked'
        return 'allowed'

    def _grace_expired(self):
        self.ensure_one()
        return bool(self.grace_until and fields.Datetime.now() > self.grace_until)

    def _banner_severity(self):
        """Return ``none``, ``warning`` or ``danger`` for the backend banner."""
        self.ensure_one()
        if self.state_source == 'unreachable':
            return 'warning'
        if self.state_source == 'cached':
            return 'danger' if self._grace_expired() else 'warning'
        if self.status in ('expired', 'suspended'):
            return 'danger'
        if self.status == 'trial':
            end = self.trial_ends_at or self.current_period_end
            if end and fields.Datetime.now() > end:
                return 'danger'
            # A trial with weeks left is not a problem yet. Warning only in the
            # run-up, so a 30-day trial does not keep a banner on screen the
            # whole time and train people to ignore it.
            if self.days_remaining <= RENEWAL_WARNING_DAYS:
                return 'warning'
            return 'none'
        if self.status == 'active' and self.days_remaining <= RENEWAL_WARNING_DAYS:
            return 'warning'
        return 'none'

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_refresh(self):
        """Refresh the snapshot by delegating to the connection record."""
        self.ensure_one()
        if not self.config_id:
            raise UserError(_("This snapshot has no connection record to refresh from."))
        return self.config_id.action_refresh_subscription()

    # ------------------------------------------------------------------
    # RPC surface used by the backend banner
    # ------------------------------------------------------------------
    @api.model
    def get_banner_payload(self):
        """Return what the OWL banner needs. Only status data, never secrets."""
        config = self.env['presenly.saas.config'].sudo()._get_or_create()
        if not config.enabled or config.guard_mode == 'off' or not config.show_banner:
            return {'visible': False}

        subscription = self.sudo().search(
            [('company_id', '=', config.company_id.id)], limit=1
        )
        if not subscription:
            return {'visible': False}

        severity = subscription._banner_severity()
        if severity == 'none':
            return {'visible': False}

        # The details screen is manager-only, so the banner offers the link
        # only to users who can actually open it.
        is_manager = self.env.user.has_group(
            'presenly_saas.group_presenly_saas_manager'
        )

        return {
            'visible': True,
            'is_manager': is_manager,
            'severity': severity,
            'status': subscription.status,
            'status_label': subscription._status_label(),
            'plan_type': subscription.plan_type,
            'tenant_code': subscription.tenant_code,
            'is_trial': subscription.is_trial,
            'days_remaining': subscription.days_remaining,
            'seat_limit': subscription.seat_limit,
            'seats_used': subscription.seats_used,
            'state_source': subscription.state_source,
            'last_sync_at': fields.Datetime.to_string(subscription.last_sync_at)
            if subscription.last_sync_at
            else False,
        }

    @api.model
    def _action_open_dashboard(self):
        """Open the snapshot form, or the connection form when none exists yet."""
        subscription = self.search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if subscription:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Presenly SaaS Subscription'),
                'res_model': self._name,
                'res_id': subscription.id,
                'view_mode': 'form',
                'target': 'current',
            }
        config = self.env['presenly.saas.config']._get_or_create()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Presenly SaaS Connection'),
            'res_model': 'presenly.saas.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }
