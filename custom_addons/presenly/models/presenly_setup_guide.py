from odoo import api, fields, models


class PresenlySetupGuide(models.TransientModel):
    """Step-by-step configuration checklist for Presenly.

    The guide is a transient (advisory) record that summarizes how many of the
    required building blocks are ready per company and links to the matching
    configuration actions. It never writes business data on its own.
    """

    _name = 'presenly.setup.guide'
    _description = 'Presenly Setup Guide'

    # ------------------------------------------------------------------
    # Scope
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )

    # ------------------------------------------------------------------
    # Step readiness (computed per company)
    # ------------------------------------------------------------------
    company_ready = fields.Boolean(compute='_compute_steps', string='Company Ready')
    location_ready = fields.Integer(compute='_compute_steps', string='Geofence-Ready Locations')
    location_total = fields.Integer(compute='_compute_steps', string='Total Locations')
    schedule_count = fields.Integer(compute='_compute_steps', string='Location Schedules')
    employee_with_location = fields.Integer(compute='_compute_steps', string='Employees with Location')
    employee_total = fields.Integer(compute='_compute_steps', string='Total Employees')
    permission_type_ready = fields.Integer(compute='_compute_steps', string='Ready Permission Types')
    permission_type_total = fields.Integer(compute='_compute_steps', string='Total Permission Types')
    leave_type_with_route = fields.Integer(compute='_compute_steps', string='Leave Types with Route')
    leave_type_total = fields.Integer(compute='_compute_steps', string='Active Leave Types')
    leave_setup_complete = fields.Boolean(compute='_compute_steps')
    all_types_routed = fields.Boolean(compute='_compute_steps')
    permission_setup_complete = fields.Boolean(compute='_compute_steps')
    overtime_route_ready = fields.Boolean(compute='_compute_steps')
    rule_total = fields.Integer(compute='_compute_steps', string='Total Approval Steps')
    rule_complete = fields.Integer(compute='_compute_steps', string='Complete Approval Steps')

    # ------------------------------------------------------------------
    # Overall readiness
    # ------------------------------------------------------------------
    step_done = fields.Integer(compute='_compute_steps', string='Steps Completed')
    step_total = fields.Integer(compute='_compute_steps', string='Total Steps')
    progress = fields.Float(compute='_compute_steps', string='Progress')
    all_ready = fields.Boolean(compute='_compute_steps', string='All Ready')

    def _company_rules(self):
        return self.env['presenly.approval.rule'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ])

    @api.depends(
        'company_id',
    )
    def _compute_steps(self):
        Rule = self.env['presenly.approval.rule']
        for guide in self:
            company = guide.company_id
            if not company:
                guide.update({
                    'step_done': 0,
                    'step_total': 8,
                    'progress': 0.0,
                    'all_ready': False,
                })
                continue

            locations = self.env['hr.work.location'].search([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ])
            location_ready = sum(
                1 for loc in locations if loc.presenly_is_geofence_ready
            )

            schedules = self.env['presenly.work.location.schedule'].search_count([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ])

            employees = self.env['hr.employee'].search([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ])
            employee_with_location = sum(
                1 for emp in employees if emp.work_location_id
            )

            permission_types = self.env['presenly.permission.type'].search([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ])
            permission_type_ready = sum(
                1 for pt in permission_types if pt.is_complete
            )

            leave_types = self.env['hr.leave.type'].with_context(
                active_test=False
            ).search([
                ('company_id', 'in', [False, company.id]),
            ]).filtered('active')
            leave_ids = leave_types.ids
            leave_with_route = len(Rule._read_group(
                [
                    ('company_id', '=', company.id),
                    ('leave_type_id', 'in', leave_ids),
                    ('active', '=', True),
                    ('is_complete', '=', True),
                ],
                ['leave_type_id'],
                ['__count'],
            )) if leave_ids else 0

            rules = guide._company_rules()
            rule_complete = sum(1 for rule in rules if rule.is_complete)
            overtime_rule = any(
                rule.is_overtime_route and rule.is_complete for rule in rules
            )

            # The Approver role is no longer required: approval rights come
            # from the Approval Routes themselves (dynamic assignment). The
            # guide's last step verifies that every active leave/permission
            # type has a complete route, which is what actually unblocks
            # submission.
            leave_type_total = len(leave_types)
            all_types_routed = bool(
                leave_types and leave_with_route == leave_type_total
            )

            # 8 steps: company, locations, geofence, schedules, employees,
            # permission types, leave types, overtime route.
            steps = [
                bool(locations),                      # 1 Company + Locations exist
                location_ready > 0,                   # 2 Geofence ready
                schedules > 0 or employee_with_location > 0,  # 3 Schedule/fallback
                employee_with_location > 0,           # 4 Employees mapped
                permission_type_ready > 0,            # 5 Permission types ready
                leave_with_route > 0,                 # 6 Leave types routed
                overtime_rule,                        # 7 Overtime routed
                all_types_routed,                     # 8 All leave types routed
            ]
            step_done = sum(1 for done in steps if done)

            guide.update({
                'company_ready': bool(locations),
                'location_total': len(locations),
                'location_ready': location_ready,
                'schedule_count': schedules,
                'employee_total': len(employees),
                'employee_with_location': employee_with_location,
                'permission_type_total': len(permission_types),
                'permission_type_ready': permission_type_ready,
                'leave_type_total': len(leave_types),
                'leave_type_with_route': leave_with_route,
                'leave_setup_complete': leave_with_route > 0,
                'all_types_routed': all_types_routed,
                'permission_setup_complete': permission_type_ready > 0,
                'overtime_route_ready': overtime_rule,
                'rule_total': len(rules),
                'rule_complete': rule_complete,
                'step_done': step_done,
                'step_total': 8,
                'progress': step_done / 8.0 * 100.0,
                'all_ready': step_done == 8,
            })

    # ------------------------------------------------------------------
    # Shortcut actions
    # ------------------------------------------------------------------
    def action_open_companies(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'base.action_res_company_form'
        )

    def action_open_locations(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'hr.hr_work_location_action'
        )

    def action_open_schedules(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'presenly.action_presenly_work_location_schedule'
        )

    def action_open_employees(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'hr.open_view_employee_list_my'
        )

    def action_open_permission_types(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'presenly.action_presenly_permission_type'
        )

    def action_open_leave_types(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'hr_holidays.open_view_holiday_status'
        )

    def action_open_approval_routes(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'presenly.action_presenly_approval_rule'
        )

    def action_open_approval_routes_leave(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'presenly.action_presenly_approval_rule_leave'
        )

    def action_open_approval_routes_permission(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'presenly.action_presenly_approval_rule_permission'
        )

    def action_open_approval_routes_overtime(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'presenly.action_presenly_approval_rule_overtime'
        )

    def action_generate_approval_routes(self):
        return self.env['ir.actions.actions']._for_xml_id(
            'presenly.action_presenly_approval_route_generate'
        )