import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

RETENTION_DAYS = 90


class PresenlySaasSyncLog(models.Model):
    """Audit trail for outbound calls to the Presenly SaaS control plane.

    Only metadata is stored. Response bodies are never persisted: the
    subscription payload carries the client name and plan of a tenant, and
    there is no operational reason to keep a copy of it here.
    """

    _name = 'presenly.saas.sync.log'
    _description = 'Presenly SaaS Sync Log'
    _order = 'create_date desc, id desc'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        ondelete='cascade',
        index=True,
    )
    endpoint = fields.Char(required=True)
    http_status = fields.Integer()
    duration_ms = fields.Integer(string='Duration (ms)')
    success = fields.Boolean()
    error_message = fields.Text()

    @api.model
    def _record(self, company, endpoint, success, http_status=None, duration_ms=None, error_message=None):
        return self.sudo().create({
            'company_id': company.id,
            'endpoint': endpoint,
            'success': success,
            'http_status': http_status or 0,
            'duration_ms': duration_ms or 0,
            'error_message': error_message,
        })

    @api.model
    def _prune(self, retention_days=RETENTION_DAYS):
        """Delete entries older than ``retention_days``."""
        deadline = fields.Datetime.now() - timedelta(days=retention_days)
        expired = self.sudo().search([('create_date', '<', deadline)])
        if expired:
            _logger.info("Presenly SaaS: pruning %s sync log entries", len(expired))
            expired.unlink()
        return True
