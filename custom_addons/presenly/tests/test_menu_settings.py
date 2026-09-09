from lxml import etree

from odoo.tests.common import TransactionCase
from odoo.tests import new_test_user


class TestPresenlyMenuAndNativeSettings(TransactionCase):
    """Approval Routes menu is reachable and native Attendance settings are
    disabled/hidden so Presenly stays the single operational path."""

    def test_approval_routes_menu_restored_and_manager_only(self):
        menu = self.env.ref('presenly.menu_presenly_approval_rules')
        self.assertTrue(menu.active)
        action = self.env.ref('presenly.action_presenly_approval_rule')
        self.assertEqual(menu.action.id, action.id)
        self.assertEqual(menu.action.res_model, 'presenly.approval.rule')
        config_menu = self.env.ref(
            'hr_attendance.menu_hr_attendance_configuration'
        )
        self.assertEqual(menu.parent_id.id, config_menu.id)
        # Only configured managers may open the global Approval Routes menu.
        self.assertIn(
            self.env.ref('presenly.group_presenly_manager'),
            menu.group_ids,
        )
        self.assertNotIn(
            self.env.ref('presenly.group_presenly_hr'),
            menu.group_ids,
        )

    def test_approval_routes_menu_visible_for_manager_not_for_hr(self):
        manager_user = new_test_user(
            self.env,
            login='menucheck_manager',
            groups='base.group_user,presenly.group_presenly_manager',
        )
        hr_user = new_test_user(
            self.env,
            login='menucheck_hr',
            groups='base.group_user,presenly.group_presenly_hr',
        )
        menu = self.env.ref('presenly.menu_presenly_approval_rules')
        # The global Approval Routes menu is only visible to managers.
        manager_visible = menu.with_user(manager_user)._filter_visible_menus()
        hr_visible = menu.with_user(hr_user)._filter_visible_menus()
        self.assertIn(menu, manager_visible)
        self.assertNotIn(menu, hr_visible)

    def test_native_attendance_settings_menu_disabled(self):
        menu = self.env.ref('hr_attendance.menu_hr_attendance_settings')
        self.assertFalse(menu.active)
        # Configuration parent still shows the Presenly entries.
        for xmlid in (
            'presenly.menu_presenly_companies',
            'presenly.menu_presenly_locations',
            'presenly.menu_presenly_work_location_schedules',
            'presenly.menu_presenly_permission_types',
            'presenly.menu_presenly_approval_rules',
        ):
            self.assertTrue(self.env.ref(xmlid).active)

    def test_native_kiosk_menus_disabled(self):
        self.assertFalse(
            self.env.ref('hr_attendance.menu_action_open_form').active
        )
        self.assertFalse(
            self.env.ref('hr_attendance.menu_hr_attendance_onboarding').active
        )
        self.assertFalse(
            self.env.ref(
                'hr_attendance.menu_hr_attendance_view_attendances_management'
            ).active
        )
        self.assertFalse(
            self.env.ref(
                'hr_attendance.menu_hr_attendance_overtime_rulesets'
            ).active
        )

    def test_res_config_kiosk_and_overtime_blocks_hidden(self):
        result = self.env['res.config.settings'].get_view(
            view_id=self.env.ref(
                'hr_attendance.res_config_settings_view_form'
            ).id,
            view_type='form',
        )
        root = etree.fromstring(result['arch'].encode())
        kiosk_mode = root.xpath(
            "//block[@name='kiosk_mode_setting_container']"
        )
        self.assertEqual(len(kiosk_mode), 1)
        self.assertEqual(kiosk_mode[0].get('invisible'), '1')
        kiosk_settings = root.xpath(
            "//block[.//field[@name='attendance_kiosk_url']]"
        )
        self.assertEqual(len(kiosk_settings), 1)
        self.assertEqual(kiosk_settings[0].get('invisible'), '1')
        overtime = root.xpath("//block[@name='overtime_settings']")
        self.assertEqual(len(overtime), 1)
        self.assertEqual(overtime[0].get('invisible'), '1')