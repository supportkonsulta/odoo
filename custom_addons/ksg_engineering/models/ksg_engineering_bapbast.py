"""BAP/BAST Engineering (FR-014, FR-014A).

Workflow: draft → waiting_approval → approved
Approval oleh Kepala Unit + digital signature.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class KsgEngineeringBapbast(models.Model):
    _name = 'ksg.engineering.bapbast'
    _description = 'BAP/BAST Engineering'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Nomor BAP/BAST', readonly=True, copy=False,
        default='New', index=True)
    project_id = fields.Many2one(
        'ksg.sales.project', string='Project', required=True,
        ondelete='cascade', index=True, tracking=True)
    periode = fields.Char(string='Periode', tracking=True)
    progress_ref_id = fields.Many2one(
        'ksg.engineering.weekly.report', string='Referensi Weekly Report',
        domain="[('project_id', '=', project_id), ('state', '=', 'done')]",
        tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_approval', 'Menunggu Approval'),
        ('approved', 'Approved'),
    ], string='Status', default='draft', tracking=True, required=True)

    # Digital signature (fallback tanpa modul Sign)
    signature_image = fields.Binary(
        string='Tanda Tangan Digital', attachment=True)
    approver_id = fields.Many2one(
        'res.users', string='Disetujui Oleh', readonly=True, tracking=True)
    tanggal_approve = fields.Datetime(
        string='Tanggal Disetujui', readonly=True, tracking=True)

    # ==================================================================
    # SEQUENCE
    # ==================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'ksg.engineering.bapbast') or 'New'
        return super().create(vals_list)

    # ==================================================================
    # ACTIONS (RULE-09: status hanya via approval resmi)
    # ==================================================================

    def action_ajukan(self):
        """Supervisor mengajukan BAP/BAST ke Kepala Unit."""
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(
                    'Hanya BAP/BAST dengan status Draft yang bisa diajukan.')
            rec.state = 'waiting_approval'
            # Schedule activity ke Kepala Unit
            kepala_units = rec.project_id.assignment_ids.filtered(
                lambda a: a.active and a.peran == 'kepala_unit'
            ).mapped('user_id')
            for user in kepala_units:
                rec.activity_schedule(
                    act_type_xmlid='ksg_engineering.activity_bapbast_approval',
                    user_id=user.id,
                    summary='BAP/BAST Menunggu Approval',
                    note=f'BAP/BAST {rec.name} menunggu persetujuan Anda.')

    def action_approve(self):
        """Kepala Unit menyetujui BAP/BAST + tanda tangan."""
        for rec in self:
            if rec.state != 'waiting_approval':
                raise ValidationError(
                    'Hanya BAP/BAST dengan status "Menunggu Approval" '
                    'yang bisa disetujui.')
            rec.write({
                'state': 'approved',
                'approver_id': self.env.user.id,
                'tanggal_approve': fields.Datetime.now(),
            })
            # Mark activities as done
            rec.activity_feedback(
                act_type_xmlid='ksg_engineering.activity_bapbast_approval',
                feedback='BAP/BAST disetujui.')
