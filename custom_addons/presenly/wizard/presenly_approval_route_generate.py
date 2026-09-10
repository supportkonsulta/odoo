from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class PresenlyApprovalRouteGenerateWizard(models.TransientModel):
    """Generate complete Approval Routes for Leave / Permission / Overtime.

    One route step (10, 20, 30, ...) is created per selected target whose
    company default scope has no complete route yet. Existing routes are kept
    untouched when ``skip_existing`` is on (default), so the wizard is safe to
    run repeatedly.
    """

    _name = 'presenly.approval.route.generate.wizard'
    _description = 'Generate Approval Routes'

    # ------------------------------------------------------------------
    # Scope and approver
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
        required=True,
    )
    apply_to = fields.Selection([
        ('all', 'All request types'),
        ('leave', 'Time Off (selected types)'),
        ('permission', 'Permission / Dispensation (selected types)'),
        ('overtime', 'Overtime'),
    ], required=True, default='all')
    leave_type_ids = fields.Many2many(
        'hr.leave.type', 'presenly_gen_leave_type_rel',
        string='Time Off Types',
        domain="[('active', '=', True), ('company_id', 'in', [False, company_id])]",
    )
    permission_type_ids = fields.Many2many(
        'presenly.permission.type', 'presenly_gen_permission_type_rel',
        string='Permission Types',
        domain="[('active', '=', True), ('company_id', '=', company_id)]",
    )
    work_location_id = fields.Many2one(
        'hr.work.location', string='Work Location Scope',
        domain="[('active', '=', True), ('company_id', '=', company_id)]",
        help='Leave empty for the company default route (recommended).',
    )
    approver_type = fields.Selection([
        ('user', 'Specific User'),
        ('employee_manager', 'Employee Manager'),
        ('unit_manager', 'Work Location Manager'),
        ('hr', 'HR Officer'),
        ('group', 'Odoo Group'),
    ], required=True, default='employee_manager', string='Approver Source')
    approver_user_id = fields.Many2one(
        'res.users', string='Specific User',
        domain="[('active', '=', True), ('company_ids', 'in', company_id)]",
    )
    approver_group_id = fields.Many2one(
        'res.groups', string='Odoo Group',
    )
    skip_existing = fields.Boolean(
        default=True, string='Skip request types that already have a complete route',
    )

    # ------------------------------------------------------------------
    # Preview lines
    # ------------------------------------------------------------------
    line_ids = fields.One2many(
        'presenly.approval.route.generate.wizard.line', 'wizard_id',
        string='Preview',
    )
    line_count = fields.Integer(compute='_compute_line_count')
    to_create_count = fields.Integer(compute='_compute_line_count')
    skipped_count = fields.Integer(compute='_compute_line_count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)
            wizard.to_create_count = len(
                wizard.line_ids.filtered(lambda line: line.status == 'to_create')
            )
            wizard.skipped_count = len(
                wizard.line_ids.filtered(lambda line: line.status == 'skipped')
            )

    # ------------------------------------------------------------------
    # Candidate target request types
    # ------------------------------------------------------------------
    def _target_candidates(self):
        """Return [(kind, target_recordset)] for the selected scope.

        Strict selection semantics:
        - Picking types in a module limits that module to the picked types.
        - While ``apply_to == 'all'``, picking types in ANY module activates
          strict mode for the other module too (empty there, no implicit
          "all types").
        - With no selection at all, every active type of the chosen modules
          is used.
        """
        self.ensure_one()
        company = self.company_id
        # _origin resolves NewId records that the web client sends during
        # onchange back to their real database ids, so scope checks and
        # domains keep working before the wizard record is saved.
        picked_leave = self.leave_type_ids._origin
        picked_permission = self.permission_type_ids._origin
        strict_all = (
            self.apply_to == 'all'
            and bool(picked_leave or picked_permission)
        )

        if self.apply_to in ('all', 'leave'):
            if picked_leave:
                leave_types = picked_leave.filtered(
                    lambda t: t.active
                    and (not t.company_id or t.company_id == company)
                )
            elif strict_all:
                leave_types = self.env['hr.leave.type']
            else:
                leave_types = self.env['hr.leave.type'].search([
                    ('active', '=', True),
                    ('company_id', 'in', [False, company.id]),
                ])
        else:
            leave_types = self.env['hr.leave.type']

        if self.apply_to in ('all', 'permission'):
            if picked_permission:
                permission_types = picked_permission.filtered(
                    lambda t: t.active and t.company_id == company
                )
            elif strict_all:
                permission_types = self.env['presenly.permission.type']
            else:
                permission_types = self.env['presenly.permission.type'].search([
                    ('active', '=', True),
                    ('company_id', '=', company.id),
                ])
        else:
            permission_types = self.env['presenly.permission.type']

        candidates = []
        for target in leave_types:
            candidates.append(('leave', target))
        for target in permission_types:
            candidates.append(('permission', target))
        # Overtime is only included when the scope is explicitly overtime, or
        # when "all" is chosen WITHOUT any type selection. If the user picks
        # specific Time Off / Permission types under "all", the strict scope
        # must exclude overtime too (nothing is generated outside the pick).
        include_overtime = (
            self.apply_to == 'overtime'
            or (self.apply_to == 'all' and not strict_all)
        )
        if include_overtime:
            candidates.append(('overtime', False))
        return candidates

    def _scope_has_route(self, kind, target):
        """True when the company-default scope already has a complete active
        route (location empty)."""
        Rule = self.env['presenly.approval.rule']
        domain = [
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('is_complete', '=', True),
            ('work_location_id', '=', False),
        ]
        if kind == 'leave':
            domain += [
                ('leave_type_id', '=', target.id),
                ('permission_type_id', '=', False),
                ('is_overtime_route', '=', False),
            ]
        elif kind == 'permission':
            domain += [
                ('permission_type_id', '=', target.id),
                ('leave_type_id', '=', False),
                ('is_overtime_route', '=', False),
            ]
        else:
            domain += [
                ('is_overtime_route', '=', True),
                ('leave_type_id', '=', False),
                ('permission_type_id', '=', False),
            ]
        return bool(Rule.search_count(domain))

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def _prepare_lines(self):
        self.ensure_one()
        self.line_ids = [(5, 0, 0)]
        commands = []
        Rule = self.env['presenly.approval.rule']
        # Per-scope next Order matching the model auto-assignment (max+10).
        next_seq = {}
        for kind, target in self._target_candidates():
            if self.skip_existing and self._scope_has_route(kind, target):
                status = 'skipped'
            else:
                status = 'to_create'
            request_id = target.id if target else False
            request_name = (
                target.display_name
                if target else 'Overtime (all employees)'
            )
            key = (kind, request_id)
            if key not in next_seq:
                values = {'company_id': self.company_id.id}
                if kind == 'leave':
                    values.update({
                        'work_location_id': self.work_location_id.id or False,
                        'permission_type_id': False,
                        'leave_type_id': request_id,
                        'is_overtime_route': False,
                    })
                elif kind == 'permission':
                    values.update({
                        'work_location_id': self.work_location_id.id or False,
                        'permission_type_id': request_id,
                        'leave_type_id': False,
                        'is_overtime_route': False,
                    })
                else:
                    values.update({
                        'work_location_id': self.work_location_id.id or False,
                        'permission_type_id': False,
                        'leave_type_id': False,
                        'is_overtime_route': True,
                    })
                next_seq[key] = Rule._current_max_sequence(values) + 10
            sequence = next_seq[key]
            next_seq[key] = sequence + 10
            commands.append((0, 0, {
                'request_kind': kind,
                'request_name': request_name,
                'request_id': request_id,
                'sequence': sequence if status == 'to_create' else 0,
                'status': status,
            }))
        self.line_ids = commands

    @api.onchange(
        'apply_to', 'company_id', 'leave_type_ids', 'permission_type_ids',
        'skip_existing',
    )
    def _onchange_prepare_lines(self):
        self._prepare_lines()

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------
    def _generate_values(self):
        """Compute fresh (kind, request_id, name) tuples from the selected
        fields, in display order. Never trusts client-sent preview lines so
        readonly line fields dropped by the web client cannot break the
        generation."""
        self.ensure_one()
        company = self.company_id
        candidates = self._target_candidates()
        out = []
        for kind, target in candidates:
            request_id = target.id if target else False
            request_name = (
                target.display_name
                if target else 'Overtime (all employees)'
            )
            if self.skip_existing and self._scope_has_route(kind, target):
                continue
            out.append((kind, request_id, request_name))
        return out

    def action_generate(self):
        self.ensure_one()
        if self.approver_type == 'user' and not self.approver_user_id:
            raise ValidationError('Select a Specific User to assign as approver.')
        if self.approver_type == 'group' and not self.approver_group_id:
            raise ValidationError('Select an Odoo Group to assign as approver.')

        pending = self._generate_values()
        if not pending:
            raise UserError(
                'No request type is waiting for a new route. Either change the '
                'selection or disable "Skip existing".'
            )

        Rule = self.env['presenly.approval.rule']
        for kind, request_id, request_name in pending:
            values = {
                'name': request_name,
                'company_id': self.company_id.id,
                'work_location_id': self.work_location_id.id or False,
                'approver_type': self.approver_type,
            }
            # Order is intentionally omitted: PresenlyApprovalRule.create()
            # auto-assigns the next free Order (+10) per scope, so generating
            # a second step in an already-routed scope never collides with the
            # unique-scope constraint.
            if kind == 'leave':
                values['leave_type_id'] = request_id
            elif kind == 'permission':
                values['permission_type_id'] = request_id
            elif kind == 'overtime':
                values['is_overtime_route'] = True
            if self.approver_type == 'user':
                values['approver_user_id'] = self.approver_user_id.id
            elif self.approver_type == 'group':
                values['approver_group_id'] = self.approver_group_id.id
            Rule.create(values)

        action = self.env['ir.actions.actions']._for_xml_id(
            'presenly.action_presenly_approval_rule'
        )
        action['name'] = f'Approval Routes — {self.company_id.display_name}'
        action['domain'] = [('company_id', '=', self.company_id.id)]
        action['context'] = {'active_test': True}
        return action


class PresenlyApprovalRouteGenerateWizardLine(models.TransientModel):
    _name = 'presenly.approval.route.generate.wizard.line'
    _description = 'Approval Route Generation Preview Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'presenly.approval.route.generate.wizard', required=True,
        ondelete='cascade',
    )
    request_kind = fields.Selection([
        ('overtime', 'Overtime'),
        ('permission', 'Permission'),
        ('leave', 'Time Off'),
    ], required=True)
    request_name = fields.Char(string='Request Type')
    request_id = fields.Integer(string='Target')
    sequence = fields.Integer(string='Order')
    status = fields.Selection([
        ('to_create', 'To Create'),
        ('skipped', 'Already Routed'),
    ], default='to_create', string='Status')