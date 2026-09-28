from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from ..services.saas_client import PresenlySaasClient


@tagged('post_install', '-at_install')
class TestPresenlySaasSettings(TransactionCase):
    """Blok Presenly SaaS di halaman Settings native.

    Field di sana hanya jembatan: nilainya dibaca dari `presenly.saas.config`
    dan ditulis kembali ke sana. Yang dijaga tes ini adalah jembatannya benar,
    dan tidak ada jalan bagi pengguna tanpa hak untuk menghapus kunci API.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Settings = cls.env['res.config.settings']

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': False,
            'environment': 'production',
            'base_url': False,
            'tenant_code': False,
            'api_key': False,
            'timeout_seconds': 10,
            'retry_count': 2,
            'guard_mode': 'warn',
            'grace_days': 7,
            'show_banner': True,
        })

    def test_compute_reads_the_stored_configuration(self):
        self.config.write({
            'enabled': True,
            'base_url': 'https://saas.example.com',
            'tenant_code': 'pelni',
            'guard_mode': 'enforce',
            'grace_days': 3,
        })

        settings = self.Settings.create({})

        self.assertTrue(settings.presenly_saas_enabled)
        self.assertEqual(settings.presenly_saas_base_url, 'https://saas.example.com')
        self.assertEqual(settings.presenly_saas_tenant_code, 'pelni')
        self.assertEqual(settings.presenly_saas_guard_mode, 'enforce')
        self.assertEqual(settings.presenly_saas_grace_days, 3)

    def test_inverse_writes_back_to_the_configuration_record(self):
        self.Settings.create({
            'presenly_saas_enabled': True,
            'presenly_saas_base_url': 'https://baru.example.com',
            'presenly_saas_tenant_code': 'ksg',
            'presenly_saas_guard_mode': 'off',
            'presenly_saas_grace_days': 21,
            'presenly_saas_show_banner': False,
        })

        self.config.invalidate_recordset()
        self.assertTrue(self.config.enabled)
        self.assertEqual(self.config.base_url, 'https://baru.example.com')
        self.assertEqual(self.config.tenant_code, 'ksg')
        self.assertEqual(self.config.guard_mode, 'off')
        self.assertEqual(self.config.grace_days, 21)
        self.assertFalse(self.config.show_banner)

    def test_computing_settings_does_not_create_a_configuration_record(self):
        # Halaman Settings dulu bisa membuat record hanya karena dibuka.
        # Sekarang compute hanya membaca.
        other_company = self.env['res.company'].create({'name': 'Perusahaan Tanpa Konfigurasi'})
        self.env['presenly.saas.config'].search(
            [('company_id', '=', other_company.id)]
        ).unlink()

        settings = self.Settings.with_company(other_company).create({})

        self.assertFalse(settings.presenly_saas_base_url)
        self.assertFalse(
            self.env['presenly.saas.config'].search(
                [('company_id', '=', other_company.id)]
            ),
            'compute seharusnya tidak membuat record konfigurasi',
        )

    def test_saving_settings_creates_the_configuration_record(self):
        other_company = self.env['res.company'].create({'name': 'Perusahaan Baru'})
        self.env['presenly.saas.config'].search(
            [('company_id', '=', other_company.id)]
        ).unlink()

        self.Settings.with_company(other_company).create({
            'presenly_saas_base_url': 'https://baru.example.com',
        })

        created = self.env['presenly.saas.config'].search(
            [('company_id', '=', other_company.id)]
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created.base_url, 'https://baru.example.com')

    def test_diagnostics_are_exposed_read_only(self):
        self.config.write({
            'last_check_status': 'failed',
            'last_check_message': 'Tidak dapat menghubungi server Presenly SaaS.',
        })

        settings = self.Settings.create({})

        self.assertEqual(settings.presenly_saas_last_check_status, 'failed')
        self.assertIn('Tidak dapat menghubungi', settings.presenly_saas_last_check_message)

    def test_manager_group_alone_cannot_open_the_native_settings(self):
        # Dokumentasi perilaku: menyetel integrasi butuh hak Settings native
        # Odoo. Group Manajer Presenly hanya mengatur akses ke blok dan kuncinya.
        presenly_manager_only = new_test_user(
            self.env,
            login='presenly_manager_without_settings_rights',
            groups='base.group_user,presenly_saas.group_presenly_saas_manager',
        )
        with self.assertRaises(AccessError):
            self.Settings.with_user(presenly_manager_only).create({})

    def test_saving_settings_does_not_erase_the_api_key(self):
        # Field API key dibatasi ke group Manajer. Kalau jembatannya menulis
        # nilai kosong yang dikirim pengguna tanpa hak, kunci yang sedang
        # dipakai akan hilang tanpa jejak.
        self.config.write({'enabled': True, 'api_key': 'kunci-yang-penting'})

        # Halaman Settings native hanya bisa dibuka pemegang hak Settings
        # (base.group_system). Group Manajer Presenly mengatur siapa yang boleh
        # melihat dan mengubah kunci, bukan siapa yang boleh membuka Settings.
        manager = new_test_user(
            self.env,
            login='presenly_settings_manager',
            groups='base.group_user,base.group_system,presenly_saas.group_presenly_saas_manager',
        )
        settings = self.Settings.with_user(manager).create({
            'presenly_saas_base_url': 'https://diubah-oleh-manajer.example.com',
        })

        self.config.invalidate_recordset()
        self.assertEqual(self.config.api_key, 'kunci-yang-penting')
        self.assertEqual(self.config.base_url, 'https://diubah-oleh-manajer.example.com')
        self.assertTrue(settings.exists())

    def test_non_manager_cannot_read_or_write_the_api_key_field(self):
        self.config.write({'api_key': 'rahasia'})
        # group_system boleh membuka halaman Settings, tetapi bukan Manajer
        # Presenly SaaS. Inilah pengguna yang harus tetap buta terhadap kunci.
        outsider = new_test_user(
            self.env,
            login='presenly_settings_outsider',
            groups='base.group_user,base.group_system',
        )

        settings = self.Settings.with_user(outsider).create({})

        # Field dibatasi group, dan Odoo menolak aksesnya dengan tegas, bukan
        # mengembalikan nilai kosong. Karena itu kunci tidak pernah sampai ke
        # klien, dan tidak bisa ikut terkirim kembali saat menyimpan.
        with self.assertRaises(AccessError):
            settings.presenly_saas_api_key
        with self.assertRaises(AccessError):
            settings.write({'presenly_saas_api_key': 'menimpa'})

        self.config.invalidate_recordset()
        self.assertEqual(self.config.api_key, 'rahasia')

    def test_test_connection_button_delegates_to_the_config_record(self):
        self.config.write({
            'enabled': True,
            'base_url': 'https://saas.example.com',
            'tenant_code': 'demo',
            'api_key': 'secret',
        })
        payload = {
            'status': 'active',
            'plan_type': 'premium',
            'schema_version': '1.0.0',
            'seat_limit': 50,
            'seats_used': 42,
        }
        settings = self.Settings.create({})

        with patch.object(PresenlySaasClient, 'get_subscription', return_value=payload):
            result = settings.action_presenly_saas_test_connection()

        self.assertEqual(result['params']['type'], 'success')
        self.config.invalidate_recordset()
        self.assertEqual(self.config.last_check_status, 'success')

    def test_refresh_button_reports_failure_without_raising(self):
        from ..services.saas_client import SaasClientError

        self.config.write({
            'enabled': True,
            'base_url': 'https://saas.example.com',
            'tenant_code': 'demo',
            'api_key': 'secret',
        })
        settings = self.Settings.create({})
        error = SaasClientError('Tidak dapat menghubungi server Presenly SaaS.', code='NETWORK_ERROR')

        with patch.object(PresenlySaasClient, 'get_subscription', side_effect=error):
            result = settings.action_presenly_saas_refresh_subscription()

        self.assertEqual(result['params']['type'], 'danger')
        self.config.invalidate_recordset()
        self.assertEqual(self.config.last_check_status, 'failed')

    def test_open_subscription_button_returns_an_action(self):
        action = self.Settings.create({}).action_presenly_saas_open_subscription()
        self.assertIn(action['res_model'], ('presenly.saas.subscription', 'presenly.saas.config'))


@tagged('post_install', '-at_install')
class TestPresenlySaasMenuStructure(TransactionCase):
    """Struktur menu: operasional di aplikasi, konfigurasi di Settings native."""

    def test_root_menu_holds_operations_and_references(self):
        """Nama menu di sini adalah teks SUMBER (Inggris).

        Terjemahan Indonesianya ada di `i18n/id.po`, jadi menguji nama sumber
        berarti menguji struktur menu, bukan bahasanya.
        """
        root = self.env.ref('presenly_saas.menu_presenly_saas_root')
        nama = root.child_id.mapped('name')
        for diharapkan in (
            'Attendance', 'Configuration', 'Reference',
            'Requests', 'Subscription', 'Sync Log', 'Timesheet',
        ):
            self.assertIn(diharapkan, nama)
        self.assertEqual(len(nama), len(set(nama)), 'ada menu kembar: %s' % nama)
        # Katalog endpoint dari `/v1/presenly/features` dibuang di 19.0.1.5.0:
        # tidak ada yang memicu penarikannya, jadi menunya selalu kosong.
        self.assertNotIn('Presenly Features', nama)

    def test_menu_presensi_dikelompokkan_jadi_satu(self):
        # Tiga menu terpisah di akar membuat pengguna menebak di mana data,
        # ringkasan, dan rekapnya berada, padahal ketiganya satu pokok.
        root = self.env.ref('presenly_saas.menu_presenly_saas_root')
        self.assertNotIn('Attendance Data', root.child_id.mapped('name'))

        presensi = self.env.ref('presenly_saas.menu_presenly_saas_attendance')
        self.assertEqual(presensi.parent_id, root)
        self.assertEqual(
            presensi.child_id.sorted(lambda m: m.sequence).mapped('name'),
            ['Attendance Data', 'Monitoring'],
        )

    def test_setiap_menu_membuka_action_atau_punya_anak(self):
        # Invarian yang sebenarnya: tidak ada menu pintu buntu. Menu kosong
        # adalah cacat, entah karena action-nya lupa didaftarkan atau anaknya
        # lupa ditambahkan.
        root = self.env.ref('presenly_saas.menu_presenly_saas_root')
        for menu in root.child_id:
            self.assertTrue(
                menu.action or menu.child_id,
                'Menu %s tidak punya action dan tidak punya anak.' % menu.name,
            )

    def test_menu_referensi_berisi_resource_inti(self):
        reference = self.env.ref('presenly_saas.menu_presenly_saas_reference')
        nama = reference.child_id.mapped('name')
        # Diperiksa sebagai isi, bukan sebagai daftar yang harus sama persis:
        # modul lain boleh menambah menu di sini, dan itu bukan kegagalan modul
        # ini. Yang perlu dijaga adalah menunya ada dan tidak kembar.
        for diharapkan in (
            'Attendance Mode', 'Projects', 'Public Holidays',
            'Shift', 'Work Day Setup', 'Work Location',
        ):
            self.assertIn(diharapkan, nama)
        self.assertEqual(len(nama), len(set(nama)), 'ada menu kembar: %s' % nama)

    def test_configuration_holds_a_single_settings_shortcut(self):
        configuration = self.env.ref('presenly_saas.menu_presenly_saas_configuration')
        self.assertEqual(
            sorted(configuration.child_id.mapped('name')),
            ['Settings'],
        )

    def test_settings_shortcut_opens_the_native_settings_action(self):
        # Pintasan, bukan form kedua: action-nya sama dengan blok di halaman
        # Settings native.
        menu = self.env.ref('presenly_saas.menu_presenly_saas_settings')
        action = self.env.ref('presenly_saas.action_presenly_saas_settings')
        self.assertEqual(menu.action, action)
        self.assertEqual(action.res_model, 'res.config.settings')
        self.assertIn('presenly_saas', action.context)

    def test_no_menu_points_to_the_removed_connection_form(self):
        # Form koneksi lama sudah tidak punya action sendiri.
        stale_action = self.env.ref(
            'presenly_saas.action_presenly_saas_open_config', raise_if_not_found=False
        )
        self.assertFalse(stale_action)

    def test_settings_block_is_registered(self):
        view = self.env.ref('presenly_saas.res_config_settings_view_form')
        self.assertEqual(view.model, 'res.config.settings')
        self.assertIn('presenly_saas_enabled', view.arch_db)
        self.assertIn('Presenly SaaS', view.arch_db)

    def test_settings_action_targets_the_native_settings_model(self):
        action = self.env.ref('presenly_saas.action_presenly_saas_settings')
        self.assertEqual(action.res_model, 'res.config.settings')
        self.assertIn('presenly_saas', action.context)

    def test_connection_form_is_read_only(self):
        # Satu tempat mengubah konfigurasi: halaman Settings.
        view = self.env.ref('presenly_saas.view_presenly_saas_config_form')
        self.assertIn('edit="false"', view.arch_db)
        self.assertIn('create="false"', view.arch_db)
