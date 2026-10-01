import logging

_logger = logging.getLogger(__name__)

_GONE_MODEL = 'hr.employee.company.wage'
_GONE_MODULE = 'presenly_company_wage'


def _table_exists(cr, qualified_name):
    cr.execute("SELECT to_regclass(%s)", (qualified_name,))
    return cr.fetchone()[0] is not None


def _column_exists(cr, table_qualified, column_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = split_part(%s, '.', 1)
           AND table_name   = split_part(%s, '.', 2)
           AND column_name  = %s
        """,
        (table_qualified, table_qualified, column_name),
    )
    return cr.fetchone() is not None


def _safe_count(cr, sql, params=()):
    cr.execute(sql, params)
    return [row[0] for row in cr.fetchall()]


def migrate(cr, version):
    """Remove leftover records from the deleted ``presenly_company_wage`` module.

    The ``presenly_company_wage`` module folder was removed without a proper
    uninstall, leaving behind database rows that still reference the deleted
    model ``hr.employee.company.wage``. Clicking those menus / actions causes
    the client to call the ORM with a model that is no longer registered,
    which surfaces as ``RPC_ERROR 404 KeyError: 'hr.employee.company.wage'``.

    Cleanup is idempotent: running it twice does not error and leaves the
    database in the same state. Only metadata tied to the deleted model is
    touched — no business data is deleted.
    """
    if not _table_exists(cr, 'public.ir_actions'):
        _logger.info(
            "ir_actions table missing; nothing to clean."
        )
        return

    # ------------------------------------------------------------------
    # 0) Resolve the ir.model id for the dead model (used by FK lookups).
    # ------------------------------------------------------------------
    model_ids = []
    if _table_exists(cr, 'public.ir_model'):
        model_ids = _safe_count(
            cr,
            "SELECT id FROM ir_model WHERE model = %s",
            (_GONE_MODEL,),
        )

    counts = {
        'menus': 0,
        'actions_res_model': 0,
        'actions_other_type': 0,
        'views': 0,
        'mail_templates': 0,
        'model_fields': 0,
        'model_access': 0,
        'rules': 0,
        'ir_model': 0,
        'data_module': 0,
        'data_orphans': 0,
    }

    # ------------------------------------------------------------------
    # 1) Catch-all: anything still bound to the deleted model by *direct*
    #    text reference (res_model / model). Run before FK-driven deletes
    #    so we don't leave dangling rows.
    # ------------------------------------------------------------------
    # 1a) ir_actions_act_window whose res_model targets the dead model
    #     (ir_actions is base table; res_model is in ir_actions_act_window)
    action_ids = []
    if _table_exists(cr, 'public.ir_actions_act_window'):
        action_ids = _safe_count(
            cr,
            "SELECT id FROM ir_actions_act_window WHERE res_model = %s",
            (_GONE_MODEL,),
        )
    counts['actions_res_model'] = len(action_ids)

    # 1b) ir_actions_server bound by model_id
    #     (server actions use model_id, not res_model)
    other_action_ids = []
    if model_ids and _table_exists(cr, 'public.ir_actions_server'):
        other_action_ids = _safe_count(
            cr,
            "SELECT id FROM ir_actions_server WHERE model_id = ANY(%s)",
            (model_ids,),
        )
        # Avoid double-counting actions already picked up by res_model
        other_action_ids = [a for a in other_action_ids if a not in set(action_ids)]
    counts['actions_other_type'] = len(other_action_ids)
    doomed_action_ids = list(set(action_ids) | set(other_action_ids))

    # 1c) ir_ui_view rows bound to the dead model
    view_ids = []
    if _table_exists(cr, 'public.ir_ui_view'):
        view_ids = _safe_count(
            cr,
            "SELECT id FROM ir_ui_view WHERE model = %s",
            (_GONE_MODEL,),
        )
    counts['views'] = len(view_ids)

    # 1d) mail.template rows bound to the dead model
    if _table_exists(cr, 'public.mail_template') \
            and _column_exists(cr, 'public.mail_template', 'model'):
        mt_ids = _safe_count(
            cr,
            "SELECT id FROM mail_template WHERE model = %s",
            (_GONE_MODEL,),
        )
    else:
        mt_ids = []
    counts['mail_templates'] = len(mt_ids)

    # 1e) ir_model_fields rows where model == dead model or relation == dead model
    field_ids = []
    if _table_exists(cr, 'public.ir_model_fields'):
        field_ids = _safe_count(
            cr,
            """
            SELECT id FROM ir_model_fields
             WHERE model = %s OR relation = %s
            """,
            (_GONE_MODEL, _GONE_MODEL),
        )
    counts['model_fields'] = len(field_ids)

    # 1f) ir_model_access rows pointing at the dead model's ir.model row
    access_ids = []
    if model_ids and _table_exists(cr, 'public.ir_model_access') \
            and _column_exists(cr, 'public.ir_model_access', 'model_id'):
        access_ids = _safe_count(
            cr,
            "SELECT id FROM ir_model_access WHERE model_id = ANY(%s)",
            (model_ids,),
        )
    counts['model_access'] = len(access_ids)

    # 1g) ir_rule rows pointing at the dead model's ir.model row
    rule_ids = []
    if model_ids and _table_exists(cr, 'public.ir_rule') \
            and _column_exists(cr, 'public.ir_rule', 'model_id'):
        rule_ids = _safe_count(
            cr,
            "SELECT id FROM ir_rule WHERE model_id = ANY(%s)",
            (model_ids,),
        )
    counts['rules'] = len(rule_ids)

    # ------------------------------------------------------------------
    # 2) Resolve menus whose `action` Reference text points at a doomed
    #    action. ir.ui.menu.action is stored as 'model,id' text, NOT a bare
    #    integer — that is the bug the previous migration missed.
    # ------------------------------------------------------------------
    menu_ids = []
    if _table_exists(cr, 'public.ir_ui_menu') \
            and _column_exists(cr, 'public.ir_ui_menu', 'action') \
            and doomed_action_ids:
        # split_part returns empty string when the comma is missing, so the
        # ::int cast cannot blow up. We also restrict to act_window text to
        # avoid matching unrelated Reference values.
        menu_ids = _safe_count(
            cr,
            """
            SELECT id
              FROM ir_ui_menu
             WHERE action LIKE 'ir.actions.act_window,%%'
               AND NULLIF(split_part(action, ',', 2), '')::int = ANY(%s)
            """,
            (doomed_action_ids,),
        )
    counts['menus'] = len(menu_ids)

    # ------------------------------------------------------------------
    # 3) Delete in dependency-safe order. Menus first (FK -> action),
    #    then access/rules (FK -> ir.model), then fields/templates/views
    #    (no FK cascade from other tables), then the model row itself.
    # ------------------------------------------------------------------
    if menu_ids:
        cr.execute(
            "DELETE FROM ir_ui_menu WHERE id = ANY(%s)",
            (menu_ids,),
        )

    if access_ids:
        cr.execute(
            "DELETE FROM ir_model_access WHERE id = ANY(%s)",
            (access_ids,),
        )

    if rule_ids:
        cr.execute(
            "DELETE FROM ir_rule WHERE id = ANY(%s)",
            (rule_ids,),
        )

    if mt_ids:
        cr.execute(
            "DELETE FROM mail_template WHERE id = ANY(%s)",
            (mt_ids,),
        )

    if field_ids:
        cr.execute(
            "DELETE FROM ir_model_fields WHERE id = ANY(%s)",
            (field_ids,),
        )

    if view_ids:
        cr.execute(
            "DELETE FROM ir_ui_view WHERE id = ANY(%s)",
            (view_ids,),
        )

    # Delete from child action tables first (they have FK to ir_actions)
    if action_ids and _table_exists(cr, 'public.ir_actions_act_window'):
        cr.execute(
            "DELETE FROM ir_actions_act_window WHERE id = ANY(%s)",
            (action_ids,),
        )

    if other_action_ids and _table_exists(cr, 'public.ir_actions_server'):
        cr.execute(
            "DELETE FROM ir_actions_server WHERE id = ANY(%s)",
            (other_action_ids,),
        )

    # Then delete from base ir_actions table
    if doomed_action_ids:
        cr.execute(
            "DELETE FROM ir_actions WHERE id = ANY(%s)",
            (doomed_action_ids,),
        )

    # ir.model must die last because the previous deletes reference its id.
    if model_ids:
        cr.execute(
            "DELETE FROM ir_model WHERE id = ANY(%s)",
            (model_ids,),
        )
    counts['ir_model'] = len(model_ids)

    # ------------------------------------------------------------------
    # 4) Purge ir_model_data rows that pointed at any of the deleted
    #    records, and (separately) all rows tagged with the dead module.
    # ------------------------------------------------------------------
    orphan_data_ids = []
    if _table_exists(cr, 'public.ir_model_data'):
        if menu_ids:
            orphan_data_ids += _safe_count(
                cr,
                "SELECT id FROM ir_model_data "
                "WHERE model = 'ir.ui.menu' AND res_id = ANY(%s)",
                (menu_ids,),
            )
        if doomed_action_ids:
            orphan_data_ids += _safe_count(
                cr,
                "SELECT id FROM ir_model_data "
                "WHERE model IN ('ir.actions.act_window','ir.actions.client',"
                "  'ir.actions.server','ir.actions.report','ir.actions.act_url') "
                "AND res_id = ANY(%s)",
                (doomed_action_ids,),
            )
        if view_ids:
            orphan_data_ids += _safe_count(
                cr,
                "SELECT id FROM ir_model_data "
                "WHERE model = 'ir.ui.view' AND res_id = ANY(%s)",
                (view_ids,),
            )
        if field_ids:
            orphan_data_ids += _safe_count(
                cr,
                "SELECT id FROM ir_model_data "
                "WHERE model = 'ir.model.fields' AND res_id = ANY(%s)",
                (field_ids,),
            )
        if access_ids:
            orphan_data_ids += _safe_count(
                cr,
                "SELECT id FROM ir_model_data "
                "WHERE model = 'ir.model.access' AND res_id = ANY(%s)",
                (access_ids,),
            )
        if rule_ids:
            orphan_data_ids += _safe_count(
                cr,
                "SELECT id FROM ir_model_data "
                "WHERE model = 'ir.rule' AND res_id = ANY(%s)",
                (rule_ids,),
            )
        if model_ids:
            orphan_data_ids += _safe_count(
                cr,
                "SELECT id FROM ir_model_data "
                "WHERE model = 'ir.model' AND res_id = ANY(%s)",
                (model_ids,),
            )

        # All XML data tagged with the deleted module
        module_data_ids = _safe_count(
            cr,
            "SELECT id FROM ir_model_data WHERE module = %s",
            (_GONE_MODULE,),
        )
        counts['data_module'] = len(module_data_ids)
        all_data_ids = list(set(orphan_data_ids) | set(module_data_ids))
        counts['data_orphans'] = len(all_data_ids)

        if all_data_ids:
            cr.execute(
                "DELETE FROM ir_model_data WHERE id = ANY(%s)",
                (all_data_ids,),
            )

    # ------------------------------------------------------------------
    # 5) Legacy cleanup driven by the deleted module's ir_model_data.
    #    Defensive: should be empty by now, but cover anything the
    #    catch-all above did not pick up (e.g. server actions with no
    #    model_id, weird reference targets, ...).
    # ------------------------------------------------------------------
    if _table_exists(cr, 'public.ir_model_data'):
        cr.execute(
            """
            SELECT model, res_id
              FROM ir_model_data
             WHERE module = %s
            """,
            (_GONE_MODULE,),
        )
        leftovers = cr.fetchall()

        for model, res_id in leftovers:
            if model == 'ir.ui.menu':
                cr.execute(
                    "DELETE FROM ir_ui_menu WHERE id = %s",
                    (res_id,),
                )
            elif model == 'ir.actions.act_window':
                cr.execute(
                    "DELETE FROM ir_actions WHERE id = %s "
                    "AND type = 'ir.actions.act_window'",
                    (res_id,),
                )
            elif model == 'ir.actions.report':
                cr.execute(
                    "DELETE FROM ir_actions WHERE id = %s "
                    "AND type = 'ir.actions.report'",
                    (res_id,),
                )
            elif model == 'ir.actions.server':
                cr.execute(
                    "DELETE FROM ir_actions WHERE id = %s "
                    "AND type = 'ir.actions.server'",
                    (res_id,),
                )
            elif model == 'ir.actions.client':
                cr.execute(
                    "DELETE FROM ir_actions WHERE id = %s "
                    "AND type = 'ir.actions.client'",
                    (res_id,),
                )
            elif model == 'ir.actions.act_url':
                cr.execute(
                    "DELETE FROM ir_actions WHERE id = %s "
                    "AND type = 'ir.actions.act_url'",
                    (res_id,),
                )
            elif model == 'ir.model.access':
                cr.execute(
                    "DELETE FROM ir_model_access WHERE id = %s",
                    (res_id,),
                )
            elif model == 'ir.rule':
                cr.execute(
                    "DELETE FROM ir_rule WHERE id = %s",
                    (res_id,),
                )
            # ir.model / ir.model.fields etc. were already cleared above.

    # ------------------------------------------------------------------
    # 6) Drop the data table if it still exists.
    # ------------------------------------------------------------------
    if _table_exists(cr, 'public.hr_employee_company_wage'):
        cr.execute("DROP TABLE hr_employee_company_wage CASCADE")

    # ------------------------------------------------------------------
    # 7) Update module state so it does not appear as broken / installed.
    # ------------------------------------------------------------------
    if _table_exists(cr, 'public.ir_module_module'):
        cr.execute(
            """
            UPDATE ir_module_module
               SET state = 'uninstalled'
             WHERE name = %s
            """,
            (_GONE_MODULE,),
        )

    _logger.info(
        "Cleaned up presenly_company_wage leftovers for %s: "
        "menus=%d actions(res_model)=%d actions(other)=%d views=%d "
        "templates=%d model_fields=%d model_access=%d rules=%d "
        "ir_model=%d data_module=%d data_orphans=%d",
        _GONE_MODEL,
        counts['menus'],
        counts['actions_res_model'],
        counts['actions_other_type'],
        counts['views'],
        counts['mail_templates'],
        counts['model_fields'],
        counts['model_access'],
        counts['rules'],
        counts['ir_model'],
        counts['data_module'],
        counts['data_orphans'],
    )
