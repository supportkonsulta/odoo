import ast
import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# `record.data` di Odoo hanya memuat field yang dideklarasikan di arch form.
# Widget peta membaca field pendampingnya (garis bujur, radius, label) dari sana.
# Kalau salah satunya disebut di `options` tetapi tidak ada di arch, widget
# membacanya sebagai `undefined` dan menyimpulkan "tidak ada koordinat" —
# petanya tidak muncul, tanpa galat apa pun.
#
# Itu pernah terjadi pada SELURUH peta di modul ini: `check_in_longitude` dan
# `check_out_longitude` lupa dicantumkan di form, sehingga tidak ada satu pun
# peta yang tampil. Tes ini memeriksa setiap field yang disebut widget peta
# benar-benar dideklarasikan di view yang memakainya.
# Semua nama opsi yang merujuk pada satu field. Opsi baru wajib didaftarkan
# di sini, kalau tidak fieldnya lolos dari pemeriksaan.
OPSI_FIELD = (
    'lon_field', 'radius_field', 'label_field', 'person_field', 'time_field',
    'office_lat_field', 'office_lon_field', 'office_radius_field',
)


@tagged('post_install', '-at_install')
class TestPresenlyMapWidgetOptions(TransactionCase):

    def _setelan_peta(self):
        """Semua pemakaian widget peta: nama view, dan opsi yang diminta."""
        hasil = []
        for view in self.env['ir.ui.view'].search([]):
            arch = view.arch_db or ''
            if 'presenly_map' not in arch:
                continue
            for pemakaian in re.finditer(r'<field[^>]*widget="presenly_map"[^>]*/>', arch, re.S):
                blok = pemakaian.group(0)
                nama_field = re.search(r'name="([a-z_]+)"', blok)
                opsi = re.search(r'options="(\{.*?\})"', blok, re.S)
                if not opsi:
                    continue
                try:
                    nilai = ast.literal_eval(opsi.group(1))
                except (ValueError, SyntaxError):
                    self.fail('opsi peta tidak bisa dibaca di %s: %s' % (view.name, opsi.group(1)))
                hasil.append((view, nama_field.group(1) if nama_field else '?', nilai))
        return hasil

    def test_ada_peta_yang_dipakai(self):
        # Kalau tidak ada satu pun, tes di bawah lolos tanpa memeriksa apa pun.
        self.assertTrue(self._setelan_peta(), 'tidak ada pemakaian widget peta')

    def test_field_pendamping_ada_di_arch(self):
        kurang = []
        for view, field, opsi in self._setelan_peta():
            dideklarasikan = set(re.findall(r'<field name="([a-z_]+)"', view.arch_db or ''))
            for nama_opsi in OPSI_FIELD:
                dirujuk = opsi.get(nama_opsi)
                if dirujuk and dirujuk not in dideklarasikan:
                    kurang.append('%s (%s): %s tidak ada di arch' % (view.name, field, dirujuk))
        self.assertEqual(
            kurang, [],
            'field yang dibutuhkan widget peta tidak dimuat view:\n  %s' % '\n  '.join(kurang),
        )

    def test_field_peta_dideklarasikan_di_archnya_sendiri(self):
        # Field tempat widget dipasang tentu harus ada, kalau tidak widgetnya
        # tidak akan pernah dirender.
        for view, field, _opsi in self._setelan_peta():
            self.assertIn(
                'name="%s"' % field, view.arch_db or '',
                'field %s tidak ada di arch %s' % (field, view.name),
            )


@tagged('post_install', '-at_install')
class TestPresenlyOfficeOnMap(TransactionCase):
    """Titik presensi harus bisa menunjukkan kantornya.

    Server mengirim `location_id` sebagai angka; tanpa ditautkan ke cermin
    lokasi kerja, peta hanya bisa menunjukkan titik pegawai, tanpa tahu di mana
    kantornya, berapa radius yang diizinkan, dan apakah absennya di dalam area.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Loc = cls.env['presenly.saas.work.location']
        cls.Log = cls.env['presenly.saas.attendance.log']

    def setUp(self):
        super().setUp()
        self.Loc.search([]).unlink()
        self.Log.search([]).unlink()

    def _lokasi(self, external_id=1, **overrides):
        values = {
            'company_id': self.company.id,
            'external_id': external_id,
            'name': 'Kantor Pusat',
            'latitude': -6.2,
            'longitude': 106.8,
            'radius_meters': 250,
        }
        values.update(overrides)
        return self.Loc.create(values)

    def _log(self, location_id=1, **overrides):
        values = {
            'company_id': self.company.id,
            'external_id': overrides.pop('external_id', 1),
            'session_key': 'k',
            'work_date': '2026-09-21',
            'status': 'closed',
            'late_minutes': 0,
            'employee_name': 'rangga',
            'location_name': 'Kantor Pusat',
            'location_id': location_id,
            'check_in_latitude': -6.201,
            'check_in_longitude': 106.801,
        }
        values.update(overrides)
        return self.Log.create(values)

    def test_kantor_tertaut_lewat_id_lokasi(self):
        lokasi = self._lokasi()
        log = self._log()
        self.assertEqual(log.work_location_id, lokasi)

    def test_koordinat_dan_radius_kantor_terbaca(self):
        self._lokasi()
        log = self._log()
        self.assertAlmostEqual(log.office_latitude, -6.2, places=5)
        self.assertAlmostEqual(log.office_longitude, 106.8, places=5)
        self.assertEqual(log.office_radius_meters, 250)

    def test_tidak_tertaut_bila_lokasinya_belum_dicerminkan(self):
        # Cermin referensi memang bisa belum ditarik. Keadaan itu harus terbaca
        # sebagai "belum ada", bukan menunjuk lokasi yang salah.
        log = self._log(location_id=99)
        self.assertFalse(log.work_location_id)
        self.assertFalse(log.office_latitude)

    def test_tidak_tertaut_bila_id_lokasi_berbeda_company(self):
        lain = self.env['res.company'].create({'name': 'Perusahaan Lain'})
        self._lokasi(external_id=1)
        self.Loc.create({
            'company_id': lain.id, 'external_id': 2, 'name': 'Kantor Lain',
            'latitude': 1.0, 'longitude': 2.0,
        })
        log = self._log(location_id=2)
        self.assertFalse(log.work_location_id, 'lokasi company lain ikut tertaut')

    def test_selalu_membaca_keadaan_sekarang(self):
        # Nilainya tidak disimpan: kalau cermin referensi ditarik setelah log,
        # kantornya harus langsung terbaca tanpa menarik ulang log-nya.
        log = self._log()
        self.assertFalse(log.office_latitude)

        self._lokasi()
        log.invalidate_recordset()
        self.assertAlmostEqual(log.office_latitude, -6.2, places=5)
