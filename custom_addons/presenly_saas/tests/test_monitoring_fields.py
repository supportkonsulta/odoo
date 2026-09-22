from datetime import datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPresenlyMonitoringFields(TransactionCase):
    """Kolom turunan yang membuat monitoring bisa dibaca.

    Pivot dan grafik pada cermin mentah hanya bisa menampilkan jumlah baris dan
    total menit. Kolom di sini membuat pertanyaan yang sebenarnya ditanyakan bisa
    dijawab langsung: berapa sesi terlambat, jam berapa orang biasanya masuk,
    dan berapa lama sesinya.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Log = cls.env['presenly.saas.attendance.log']

    def setUp(self):
        super().setUp()
        self.Log.search([]).unlink()

    def _baris(self, **overrides):
        values = {
            'company_id': self.company.id,
            'external_id': overrides.pop('external_id', 1),
            'session_key': 'k',
            'work_date': '2026-09-21',
            'status': 'closed',
            'late_minutes': 0,
            'employee_name': 'rangga',
        }
        values.update(overrides)
        return self.Log.create(values)

    def test_terlambat_dihitung_dari_menit(self):
        self.assertTrue(self._baris(late_minutes=1).is_late)
        self.assertFalse(self._baris(late_minutes=0, external_id=2).is_late)

    def test_penghitung_sesi_terlambat(self):
        # Kolomnya dipakai sebagai ukuran pivot, jadi nilainya harus 1 atau 0,
        # bukan True/False.
        self.assertEqual(self._baris(late_minutes=5).late_session_count, 1)
        self.assertEqual(self._baris(late_minutes=0, external_id=2).late_session_count, 0)

    def test_jam_masuk_sebagai_desimal(self):
        baris = self._baris(check_in_time=datetime(2026, 9, 21, 7, 30, 0))
        self.assertEqual(baris.check_in_hour, 7.5)

    def test_jam_masuk_nol_bila_tidak_ada_waktu(self):
        self.assertEqual(self._baris().check_in_hour, 0.0)

    def test_lama_sesi(self):
        baris = self._baris(
            check_in_time=datetime(2026, 9, 21, 8, 0, 0),
            check_out_time=datetime(2026, 9, 21, 12, 30, 0),
        )
        self.assertEqual(baris.session_hours, 4.5)

    def test_shift_lewat_tengah_malam_tidak_negatif(self):
        # 22:00 -> 02:00 bisa berarti 4 jam atau -20 jam. Menebak lebih buruk
        # daripada mengosongkan.
        baris = self._baris(
            check_in_time=datetime(2026, 9, 21, 22, 0, 0),
            check_out_time=datetime(2026, 9, 22, 2, 0, 0),
        )
        self.assertEqual(baris.session_hours, 4.0)

    def test_check_out_terlewat_tidak_dihitung(self):
        # Data nyata punya sesi 18 Sep: masuk 10:02, pulang 21 Sep 01:47 — 63 jam.
        # Secara aritmetika benar, tetapi itu bukan lama kerja, dan
        # menjumlahkannya menggelembungkan total di pivot.
        baris = self._baris(
            check_in_time=datetime(2026, 9, 18, 10, 2, 0),
            check_out_time=datetime(2026, 9, 21, 1, 47, 0),
        )
        self.assertEqual(baris.session_hours, 0.0)

    def test_sesi_tepat_24_jam_masih_dihitung(self):
        baris = self._baris(
            check_in_time=datetime(2026, 9, 21, 8, 0, 0),
            check_out_time=datetime(2026, 9, 22, 8, 0, 0),
        )
        self.assertEqual(baris.session_hours, 24.0)

    def test_lama_sesi_nol_bila_salah_satu_waktu_kosong(self):
        baris = self._baris(check_in_time=datetime(2026, 9, 21, 8, 0, 0))
        self.assertEqual(baris.session_hours, 0.0)

    def test_dapat_dipakai_di_read_group(self):
        # Pivot dan grafik memakai read_group. Kalau kolomnya tidak punya
        # `aggregator`, permintaan berikut akan gagal dan tampilannya kosong.
        self._baris(late_minutes=10, external_id=1)
        self._baris(late_minutes=0, external_id=2)

        hasil = self.Log.read_group(
            domain=[],
            fields=['late_session_count:sum', 'late_minutes:sum'],
            groupby=['employee_name'],
        )
        self.assertEqual(len(hasil), 1)
        self.assertEqual(hasil[0]['late_session_count'], 1)
        self.assertEqual(hasil[0]['late_minutes'], 10)


@tagged('post_install', '-at_install')
class TestPresenlyReadableFields(TransactionCase):
    """Kolom turunan yang membuat form presensi bisa dibaca.

    Angka mentah dari server tetap disimpan apa adanya, tetapi di form angkanya
    tidak menjawab apa pun: "13587796.00" meter dan "250.00" meter harus
    dibandingkan sendiri oleh pembacanya. Kolom di sini memisahkan fakta
    (kalimat jarak) dari putusan (di dalam atau di luar geofence).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Log = cls.env['presenly.saas.attendance.log']

    def setUp(self):
        super().setUp()
        self.Log.search([]).unlink()

    def _baris(self, **overrides):
        values = {
            'company_id': self.company.id,
            'external_id': overrides.pop('external_id', 1),
            'session_key': 'k',
            'work_date': '2026-09-21',
            'status': 'closed',
            'employee_name': 'rangga',
        }
        values.update(overrides)
        return self.Log.create(values)

    def test_jarak_di_bawah_satu_kilometer_memakai_meter(self):
        log = self._baris(check_in_distance_meters=320, check_in_allowed_radius_meters=250)
        self.assertEqual(log.check_in_distance_text, '320 m from the office, allowed 250 m')

    def test_jarak_beberapa_kilometer_memakai_satu_angka_di_belakang_koma(self):
        log = self._baris(check_in_distance_meters=1500, check_in_allowed_radius_meters=250)
        self.assertEqual(log.check_in_distance_text, '1.5 km from the office, allowed 250 m')

    def test_jarak_jauh_memakai_spasi_sebagai_pemisah_ribuan(self):
        # Titik dan koma berarti hal berbeda di dua bahasa yang dipakai modul ini,
        # jadi keduanya menyesatkan di salah satu bahasa.
        log = self._baris(check_in_distance_meters=13587796, check_in_allowed_radius_meters=250)
        self.assertEqual(log.check_in_distance_text, '13\u00a0588 km from the office, allowed 250 m')
        # Angkanya sendiri tidak memakai koma maupun titik sebagai pemisah ribuan.
        angkanya = log.check_in_distance_text.split(' km')[0]
        self.assertNotIn(',', angkanya)
        self.assertNotIn('.', angkanya)

    def test_radius_yang_tidak_diketahui_tidak_disebut(self):
        log = self._baris(check_in_distance_meters=320)
        self.assertEqual(log.check_in_distance_text, '320 m from the office')

    def test_tanpa_jarak_tidak_ada_kalimatnya(self):
        log = self._baris()
        self.assertFalse(log.check_in_distance_text)
        self.assertEqual(log.check_in_radius_state, 'unknown')

    def test_putusan_geofence(self):
        dalam = self._baris(external_id=11, check_in_distance_meters=100, check_in_allowed_radius_meters=250)
        self.assertEqual(dalam.check_in_radius_state, 'inside')

        # Tepat di batas masih dihitung di dalam: radiusnya sendiri termasuk.
        batas = self._baris(external_id=12, check_in_distance_meters=250, check_in_allowed_radius_meters=250)
        self.assertEqual(batas.check_in_radius_state, 'inside')

        luar = self._baris(external_id=13, check_in_distance_meters=251, check_in_allowed_radius_meters=250)
        self.assertEqual(luar.check_in_radius_state, 'outside')

    def test_tidak_diketahui_bukan_berarti_di_luar(self):
        # Radius nol atau jarak kosong bukan bukti pelanggaran geofence.
        log = self._baris(check_in_distance_meters=100, check_in_allowed_radius_meters=0)
        self.assertEqual(log.check_in_radius_state, 'unknown')

    def test_putusan_bisa_disaring(self):
        # `store=True` bukan pilihan gaya: tanpa itu saringan ini tidak bisa
        # dijawab Odoo.
        luar = self._baris(external_id=21, check_in_distance_meters=900, check_in_allowed_radius_meters=250)
        self._baris(external_id=22, check_in_distance_meters=10, check_in_allowed_radius_meters=250)
        ditemukan = self.Log.search([('check_in_radius_state', '=', 'outside')])
        self.assertEqual(ditemukan, luar)

    def test_keterlambatan_ditulis_dalam_jam_dan_menit(self):
        self.assertEqual(self._baris(external_id=31, late_minutes=45).late_text, '45 min late')
        self.assertEqual(self._baris(external_id=32, late_minutes=571).late_text, '9h 31m late')

    def test_tepat_waktu_ditulis_bukan_dikosongkan(self):
        # Baris kosong membuat pembaca menebak apakah artinya tepat waktu atau
        # datanya tidak ada.
        self.assertEqual(self._baris(external_id=41, late_minutes=0).late_text, 'On time')

    def test_lama_sesi_ditulis_dalam_jam_dan_menit(self):
        log = self._baris(
            external_id=51,
            check_in_time=datetime(2026, 9, 21, 1, 0, 0),
            check_out_time=datetime(2026, 9, 21, 9, 30, 0),
        )
        self.assertEqual(log.session_hours, 8.5)
        self.assertEqual(log.session_text, '8h 30m')

    def test_sesi_yang_tidak_bisa_dihitung_tidak_punya_teks(self):
        log = self._baris(external_id=61, check_in_time=datetime(2026, 9, 21, 1, 0, 0))
        self.assertFalse(log.session_text)


@tagged('post_install', '-at_install')
class TestPresenlyPivotMeasures(TransactionCase):
    """Kolom id mentah tidak boleh muncul sebagai ukuran pivot.

    Odoo menyusun daftar "Measures" dari setiap field numerik yang
    `aggregator`-nya truthy (`addons/web/static/src/views/utils.js`). Tanpa
    `aggregator=False`, seluruh kolom id mentah ikut terdaftar di antarmuka —
    angka yang tidak bisa dipakai pengguna untuk apa pun. Dulu itu memang
    terjadi, dan hanya terlihat setelah pivotnya dibuka.
    """

    # Field yang memang harus jadi ukuran: pertanyaan yang dijawab monitoring.
    UKURAN_DIHARAPKAN = {'late_session_count', 'late_minutes', 'check_in_hour', 'session_hours'}

    def _ukuran_pivot(self, model_name):
        model = self.env[model_name]
        return {
            nama for nama, field in model._fields.items()
            if field.type in ('integer', 'float', 'monetary')
            and getattr(field, 'store', False)
            and field.aggregator
            and nama != 'id'
        }

    def test_id_mentah_bukan_ukuran_pivot(self):
        ukuran = self._ukuran_pivot('presenly.saas.attendance.log')
        terlarang = {
            'external_id', 'user_id', 'location_id', 'shift_id',
            'check_in_mode_id', 'check_out_mode_id',
            'schedule_id', 'schedule_segment_id',
            # Koordinat: menjumlahkan latitude tidak berarti apa pun.
            'check_in_latitude', 'check_in_longitude',
            'check_out_latitude', 'check_out_longitude',
        }
        bocor = sorted(ukuran & terlarang)
        self.assertEqual(bocor, [], 'id mentah muncul sebagai ukuran pivot: %s' % bocor)

    def test_ukuran_yang_berguna_tetap_ada(self):
        ukuran = self._ukuran_pivot('presenly.saas.attendance.log')
        for nama in self.UKURAN_DIHARAPKAN:
            self.assertIn(nama, ukuran, '%s hilang dari ukuran pivot' % nama)

    def test_field_jadwal_sudah_tidak_ada(self):
        # Server tidak lagi mengirimnya, jadi menyimpannya hanya menambah kolom
        # mati yang selalu bernilai nol.
        fields = self.env['presenly.saas.attendance.log']._fields
        for nama in ('schedule_id', 'schedule_segment_id', 'schedule_source'):
            self.assertNotIn(nama, fields)

    def test_cermin_lain_juga_tidak_menawarkan_external_id(self):
        # Mixin dipakai seluruh cermin, jadi satu perbaikan berlaku untuk semua.
        for model_name in ('presenly.saas.employee', 'presenly.saas.timesheet',
                           'presenly.saas.leave', 'presenly.saas.project'):
            ukuran = self._ukuran_pivot(model_name)
            self.assertNotIn('external_id', ukuran, model_name)
