from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.presenly_saas_subscription import parse_datetime


@tagged('post_install', '-at_install')
class TestPresenlySaasPlanFeatures(TransactionCase):
    """Konsumsi profil perusahaan, paket, dan fitur dari API eksternal.

    Aturan yang dijaga: ketiadaan data tidak pernah mencabut akses. `False` dari
    `has_feature()` hanya boleh keluar bila server benar-benar mengirim
    `included: false`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Subscription = cls.env['presenly.saas.subscription']
        cls.guard = cls.env['presenly.saas.guard']

    def setUp(self):
        super().setUp()
        self.Subscription.search([]).unlink()

    def snapshot(self, **overrides):
        values = {
            'company_id': self.company.id,
            'config_id': self.config.id,
            'tenant_code': 'pelni',
            'client_name': 'Pelni',
            'plan_type': 'trial_plan',
            'status': 'active',
            'state_source': 'live',
            'last_sync_at': fields_now(),
            'plan_features': [],
        }
        values.update(overrides)
        return self.Subscription.create(values)

    # ------------------------------------------------------------------
    # Penyimpanan payload
    # ------------------------------------------------------------------
    def test_payload_profile_and_plan_are_stored(self):
        subscription = self.Subscription._sync_from_payload(self.config, {
            'tenant_code': 'pelni',
            'client_name': 'Pelni',
            'plan_type': 'premium',
            'plan_name': 'Premium',
            'plan_registered': True,
            'tenant_email': 'support@pelni.id',
            'tenant_whatsapp': '0812736564723',
            'tenant_business_sector': 'Pelayaran',
            'tenant_reference': 'kontrak-2026',
            'tenant_employee_count': 30,
            'tenant_joined_at': '2026-09-17T15:57:50.000Z',
            'status': 'active',
            'schema_version': '1.0.0',
        })

        self.assertEqual(subscription.plan_name, 'Premium')
        self.assertTrue(subscription.plan_registered)
        self.assertEqual(subscription.tenant_email, 'support@pelni.id')
        self.assertEqual(subscription.tenant_whatsapp, '0812736564723')
        self.assertEqual(subscription.tenant_business_sector, 'Pelayaran')
        self.assertEqual(subscription.tenant_reference, 'kontrak-2026')
        self.assertEqual(subscription.tenant_employee_count, 30)
        self.assertEqual(
            subscription.tenant_joined_at,
            parse_datetime('2026-09-17T15:57:50.000Z'),
        )

    def test_payload_without_profile_fields_stays_empty(self):
        subscription = self.Subscription._sync_from_payload(self.config, {
            'tenant_code': 'pelni', 'client_name': 'Pelni', 'status': 'trial',
        })

        self.assertFalse(subscription.tenant_email)
        self.assertFalse(subscription.plan_name)
        self.assertEqual(subscription.feature_count, 0)

    # ------------------------------------------------------------------
    # Pembersihan daftar fitur
    # ------------------------------------------------------------------
    def test_sanitize_feature_list_keeps_only_well_formed_entries(self):
        cleaned = self.Subscription._sanitize_features([
            {'code': 'attendance', 'label': 'Presensi', 'group': 'Presensi', 'included': True},
            {'label': 'tanpa kode'},
            'bukan dict',
            None,
            {'code': 123},
            {'code': 'overtime'},
        ])

        self.assertEqual([f['code'] for f in cleaned], ['attendance', 'overtime'])
        # Kode tanpa label memakai kodenya sendiri, dan tanpa `included`
        # dianggap tidak termasuk supaya tidak ada fitur yang terbuka diam-diam.
        self.assertEqual(cleaned[1]['label'], 'overtime')
        self.assertFalse(cleaned[1]['included'])

    def test_sanitize_rejects_non_list(self):
        self.assertEqual(self.Subscription._sanitize_features(None), [])
        self.assertEqual(self.Subscription._sanitize_features({'a': 1}), [])

    # ------------------------------------------------------------------
    # Ringkasan fitur
    # ------------------------------------------------------------------
    def test_feature_summary_counts_and_splits(self):
        subscription = self.snapshot(plan_features=[
            {'code': 'attendance', 'label': 'Presensi', 'group': 'Presensi', 'included': True},
            {'code': 'overtime', 'label': 'Lembur', 'group': 'Pengajuan', 'included': True},
            {'code': 'face_recognition', 'label': 'Wajah', 'group': 'Presensi', 'included': False},
        ])

        self.assertEqual(subscription.feature_count, 3)
        self.assertEqual(subscription.included_feature_count, 2)
        self.assertEqual(subscription.included_feature_codes, 'attendance, overtime')
        self.assertEqual(subscription.missing_feature_codes, 'face_recognition')
        self.assertIn('Presensi', subscription.features_summary)
        self.assertIn('Wajah', subscription.features_summary)

    def test_feature_summary_is_empty_without_features(self):
        subscription = self.snapshot()
        self.assertEqual(subscription.feature_count, 0)
        self.assertFalse(subscription.features_summary)

    # ------------------------------------------------------------------
    # has_feature: aturan konservatif
    # ------------------------------------------------------------------
    def test_has_feature_true_when_included(self):
        self.snapshot(plan_features=[
            {'code': 'attendance', 'label': 'Presensi', 'included': True},
        ])
        self.assertTrue(self.guard.has_feature('attendance'))

    def test_has_feature_false_when_server_says_not_included(self):
        self.snapshot(plan_features=[
            {'code': 'face_recognition', 'label': 'Wajah', 'included': False},
        ])
        self.assertFalse(self.guard.has_feature('face_recognition'))

    def test_has_feature_true_without_any_snapshot(self):
        # Instalasi lama belum pernah menyegarkan: field fitur masih kosong.
        self.assertTrue(self.guard.has_feature('apa_saja'))

    def test_has_feature_true_when_snapshot_has_no_feature_list(self):
        self.snapshot(plan_features=[])
        self.assertTrue(self.guard.has_feature('apa_saja'))

    def test_has_feature_true_for_unknown_code(self):
        self.snapshot(plan_features=[
            {'code': 'attendance', 'label': 'Presensi', 'included': True},
        ])
        self.assertTrue(self.guard.has_feature('fitur_yang_belum_dikenal'))

    def test_has_feature_without_code_is_true(self):
        self.snapshot(plan_features=[
            {'code': 'attendance', 'label': 'Presensi', 'included': False},
        ])
        self.assertTrue(self.guard.has_feature())
        self.assertTrue(self.guard.has_feature(None))

    # ------------------------------------------------------------------
    # Guard state
    # ------------------------------------------------------------------
    def test_state_reports_missing_features(self):
        self.snapshot(
            plan_name='Premium',
            plan_features=[
                {'code': 'attendance', 'label': 'Presensi', 'included': True},
                {'code': 'overtime', 'label': 'Lembur', 'included': False},
            ],
        )

        state = self.guard.state()

        self.assertEqual(state['plan_name'], 'Premium')
        self.assertEqual(state['missing_features'], ['overtime'])

    def test_state_without_snapshot_reports_no_missing_features(self):
        state = self.guard.state()
        self.assertFalse(state['has_snapshot'])
        self.assertEqual(state['missing_features'], [])
        self.assertFalse(state['plan_name'])

    def test_missing_features_helper(self):
        self.snapshot(plan_features=[
            {'code': 'attendance', 'label': 'Presensi', 'included': True},
            {'code': 'leave', 'label': 'Cuti', 'included': False},
        ])
        self.assertEqual(self.guard.missing_features(), ['leave'])

    # ------------------------------------------------------------------
    # Fitur tidak memblokir operasi
    # ------------------------------------------------------------------
    def test_missing_feature_does_not_block_when_guard_enforces(self):
        # Keputusan produk: mode enforce menegakkan STATUS langganan, bukan
        # fitur. Menegakkan fitur butuh modul pemanggil yang belum ada.
        self.config.write({'enabled': True, 'guard_mode': 'enforce'})
        self.snapshot(
            status='active',
            plan_features=[{'code': 'overtime', 'label': 'Lembur', 'included': False}],
        )

        self.assertFalse(self.guard.has_feature('overtime'))
        self.assertTrue(self.guard.is_allowed('overtime.create'))


def fields_now():
    from odoo import fields
    return fields.Datetime.now()
