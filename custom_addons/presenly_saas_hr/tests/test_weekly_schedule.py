from unittest import mock

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPresenlyWeeklySchedule(TransactionCase):
    """Pola mingguan: lokasi kerja dan shift per hari.

    Yang dijaga tes ini adalah penghapusan berskop: baris yang hilang dari respons
    memang harus hilang, tetapi hanya milik pegawai yang muncul di respons itu.
    Kalau tarikannya terpotong, pegawai yang tidak terlihat tidak boleh ikut
    kehilangan jadwalnya.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Schedule = cls.env['presenly.saas.employee.schedule']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)

    def _baris(self, external_id, nopeg, hari, lokasi='Lokasi Uji', kerja=True):
        return {
            'id': external_id,
            'day_of_week': hari,
            'is_workday': kerja,
            'location': {'id': 500, 'name': lokasi},
            'shift': {'id': 9, 'name': 'Normal 1'},
            'employee': {'id': 1, 'nopeg': nopeg, 'name': nopeg},
            'priority': 0,
            'status': 'active',
            'valid_from': None,
            'valid_until': None,
        }

    def _tarik(self, baris):
        with mock.patch.object(type(self.config), '_client', lambda self: mock.Mock()), \
             mock.patch.object(type(self.config), '_fetch_pages', lambda *a, **k: (baris, {}, 1)):
            return self.config._pull_schedules()

    def test_jadwal_disimpan_dan_ditautkan_ke_pegawai(self):
        hr = self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-jadwal'})

        ringkas, error = self._tarik([
            self._baris(1, 'uji-jadwal', 'mon'),
            self._baris(2, 'uji-jadwal', 'tue', kerja=False),
        ])

        self.assertFalse(error)
        self.assertEqual(ringkas['created'], 2)
        senin = self.Schedule.search([
            ('employee_nopeg', '=', 'uji-jadwal'), ('day_of_week', '=', 'mon'),
        ])
        self.assertEqual(senin.location_name, 'Lokasi Uji')
        self.assertEqual(senin.shift_name, 'Normal 1')
        self.assertEqual(senin.hr_employee_id, hr)
        self.assertIn('Lokasi Uji', senin.name)

    def test_baris_yang_hilang_dihapus_untuk_pegawai_yang_terlihat(self):
        self.Hr.create({'name': 'Pegawai Uji', 'presenly_nopeg': 'uji-jadwal'})
        self._tarik([self._baris(1, 'uji-jadwal', 'mon'), self._baris(2, 'uji-jadwal', 'tue')])

        # Respons berikutnya hanya memuat hari Senin.
        ringkas, _error = self._tarik([self._baris(1, 'uji-jadwal', 'mon')])

        self.assertEqual(ringkas['removed'], 1)
        self.assertEqual(
            self.Schedule.search([('employee_nopeg', '=', 'uji-jadwal')]).mapped('day_of_week'),
            ['mon'],
        )

    def test_pegawai_yang_tidak_terlihat_tidak_kehilangan_jadwalnya(self):
        """Tarikan yang terpotong tidak boleh menghapus jadwal orang lain."""
        self.Hr.create({'name': 'Satu', 'presenly_nopeg': 'uji-satu'})
        self.Hr.create({'name': 'Dua', 'presenly_nopeg': 'uji-dua'})
        self._tarik([self._baris(1, 'uji-satu', 'mon'), self._baris(2, 'uji-dua', 'mon')])

        ringkas, _error = self._tarik([self._baris(1, 'uji-satu', 'mon')])

        self.assertEqual(ringkas['removed'], 0)
        self.assertTrue(
            self.Schedule.search([('employee_nopeg', '=', 'uji-dua')]),
            'jadwal pegawai yang tidak muncul di respons dibiarkan',
        )

    def test_pegawai_yang_belum_ada_dihitung_bukan_dipaksakan(self):
        ringkas, error = self._tarik([self._baris(1, 'uji-belum-tersinkron', 'mon')])

        self.assertFalse(error)
        self.assertEqual(ringkas['without_employee'], 1)
        self.assertFalse(
            self.Schedule.search([('employee_nopeg', '=', 'uji-belum-tersinkron')]).hr_employee_id,
        )
