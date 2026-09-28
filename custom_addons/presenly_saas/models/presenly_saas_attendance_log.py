import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


def parse_datetime(value):
    """Konversi ISO-8601 dari API menjadi datetime UTC naive."""
    from .presenly_saas_subscription import parse_datetime as _parse
    return _parse(value)


class PresenlySaasAttendanceLog(models.Model):
    """Cermin log presensi dari `GET /v1/presenly/attendance-logs`.

    Ini **cermin**, bukan arsip. Setiap penarikan mengganti baris untuk periode
    yang sama, sehingga tidak menumpuk dan tidak mencampur data basi dengan data
    baru. Field bersarang dari API disimpan pada `raw_payload` supaya tidak ada
    informasi yang hilang, sementara kolom yang dipakai menampilkan diringkas di
    sini.

    Modul ini tidak menyentuh `hr.attendance`. Data ini hanya untuk dilihat dan
    diekspor dari Odoo, sumber kebenarannya tetap Presenly SaaS.
    """

    _name = 'presenly.saas.attendance.log'
    _description = 'Presenly Attendance Log (mirror)'
    _order = 'work_date desc, check_in_time desc, id desc'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    # Punya deklarasi sendiri, jadi `aggregator=False` dari mixin tidak berlaku
    # di sini dan harus diulang.
    external_id = fields.Integer(string='Session ID', required=True, index=True,
                                 aggregator=False)
    session_key = fields.Char(index=True)
    work_date = fields.Date(index=True)

    user_id = fields.Integer(
        aggregator=False,string='Employee ID (SaaS)')
    employee_name = fields.Char(string='Employee')
    employee_nopeg = fields.Char(string='Nopeg')
    project_name = fields.Char(string='Project')

    location_id = fields.Integer(
        aggregator=False,string='Location ID (SaaS)')
    location_name = fields.Char(string='Location')
    tenant_client_name = fields.Char(string='Internal Company')

    shift_id = fields.Integer(
        aggregator=False,string='Shift ID (SaaS)')
    shift_name = fields.Char(string='Shift')


    status = fields.Selection(
        [('open', 'Open'), ('closed', 'Finished'), ('alpha', 'Absence')],
        string='Status',
    )
    late_minutes = fields.Integer(string='Late (minutes)')
    is_overtime = fields.Boolean(string='Overtime Session')

    check_in_time = fields.Datetime()
    check_out_time = fields.Datetime()
    # Koordinat bukan ukuran: menjumlahkan latitude menghasilkan angka yang tidak
    # berarti apa pun. Kalau dijadikan ukuran, keduanya ikut muncul di daftar
    # "Measures" dan mengundang pengguna memakainya.
    check_in_latitude = fields.Float(digits=(10, 7), aggregator=False)
    check_in_longitude = fields.Float(digits=(10, 7), aggregator=False)
    # Jarak dan radius justru berguna, tapi sebagai RATA-RATA: totalnya tidak
    # berarti, sedangkan rata-rata jarak dibanding radius menunjukkan seberapa
    # dekat pegawai biasanya mengabsen.
    #
    # Tanpa angka di belakang koma: satuan meter tidak dibaca sampai seperseratus,
    # dan "13587796.00" di daftar hanya menambah panjang tanpa menambah arti.
    # Angka yang enak dibaca ada di `check_in_distance_text` dan
    # `check_in_radius_state`.
    check_in_distance_meters = fields.Float(
        string='Check-in Distance (m)', digits=(16, 0), aggregator='avg'
    )
    check_in_allowed_radius_meters = fields.Float(
        string='Check-in Radius (m)', digits=(16, 0), aggregator='avg'
    )
    check_in_mode_id = fields.Integer(
        aggregator=False,)
    check_in_mode_name = fields.Char(string='Check-in Mode')
    check_out_latitude = fields.Float(digits=(10, 7), aggregator=False)
    check_out_longitude = fields.Float(digits=(10, 7), aggregator=False)
    check_out_distance_meters = fields.Float(
        string='Check-out Distance (m)', digits=(16, 0), aggregator='avg'
    )
    check_out_allowed_radius_meters = fields.Float(
        string='Check-out Radius (m)', digits=(16, 0), aggregator='avg'
    )
    check_out_mode_id = fields.Integer(
        aggregator=False,)
    check_out_mode_name = fields.Char(string='Check-out Mode')

    source_created_at = fields.Datetime(string='Created on SaaS')
    source_updated_at = fields.Datetime(string='Updated on SaaS')
    fetched_at = fields.Datetime(readonly=True, index=True)

    # Field bersarang dari API disimpan apa adanya, sehingga tidak ada yang
    # hilang hanya karena belum dibuatkan kolomnya.
    raw_payload = fields.Json(string='Raw Payload')

    _company_external_uniq = models.Constraint(
        'unique(company_id, external_id)',
        'A session may only be mirrored once per company.',
    )

    # ------------------------------------------------------------------
    # Lokasi kerja yang bersangkutan
    # ------------------------------------------------------------------
    # Server mengirim `location_id` sebagai angka. Untuk bisa menampilkan
    # kantornya di peta, angkanya ditautkan ke cermin lokasi kerja — di sana ada
    # koordinat pusat dan radius geofence-nya.
    #
    # Tidak disimpan (`store=False`): cermin referensi bisa ditarik kapan saja,
    # dan nilai tersimpan akan basi sampai log-nya ditulis ulang. Radas `related`
    # selalu membaca keadaan sekarang.
    work_location_id = fields.Many2one(
        'presenly.saas.work.location',
        string='Office',
        compute='_compute_office',
    )
    # Dihitung bersama `work_location_id`, bukan lewat `related`. Radas `related`
    # ke field yang tidak disimpan membuat Odoo tidak bisa menentukan kapan harus
    # menghitung ulang, dan itu memunculkan peringatan:
    #
    #   "Field '...work_location_id' in dependency of '...office_latitude' should
    #    be searchable ... You should either make the field searchable, or
    #    simplify the field dependency."
    #
    # Menghitungnya di satu tempat menghapus ketergantungan itu sekaligus membuat
    # nilainya selalu dibaca dari keadaan sekarang.
    office_latitude = fields.Float(compute='_compute_office')
    office_longitude = fields.Float(compute='_compute_office')
    office_radius_meters = fields.Integer(compute='_compute_office')

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None,
                        count_limit=None):
        """Segarkan cermin sebelum daftarnya dibaca.

        Model ini tidak mewarisi `presenly.saas.mirror.mixin` — radas penulisannya
        sendiri — sehingga pemicu yang dipasang di mixin itu tidak berlaku di
        sini. Tanpa penimpaan ini, membuka daftar presensi tidak menarik apa pun,
        dan absensi baru dari aplikasi tidak pernah muncul.
        """
        # Hanya halaman pertama. Menggulir, mengurutkan ulang, dan mencari juga
        # memanggil metode ini; tanpa syarat ini satu kali membuka daftar yang
        # panjang bisa memicu belasan penarikan.
        if not offset:
            self.env['presenly.saas.config']._refresh_from_page()
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit, order=order,
            count_limit=count_limit,
        )

    @api.depends('location_id', 'company_id')
    def _compute_office(self):
        Lokasi = self.env['presenly.saas.work.location']
        peta = {}
        for company in self.company_id:
            for lokasi in Lokasi.search([('company_id', '=', company.id)]):
                peta[(company.id, lokasi.external_id)] = lokasi
        for log in self:
            # Lokasinya bisa belum tercermin, atau tidak ada sama sekali. Nilai
            # kosong adalah jawaban yang benar untuk itu — bukan alasan gagal.
            lokasi = peta.get((log.company_id.id, log.location_id))
            log.work_location_id = lokasi
            log.office_latitude = lokasi.latitude if lokasi else 0.0
            log.office_longitude = lokasi.longitude if lokasi else 0.0
            log.office_radius_meters = lokasi.radius_meters if lokasi else 0

    # ------------------------------------------------------------------
    # Kolom turunan untuk monitoring
    # ------------------------------------------------------------------
    # Pivot dan grafik pada cermin mentah hanya bisa menampilkan jumlah baris dan
    # total menit. Ketiga kolom ini membuat pertanyaan yang sebenarnya ditanyakan
    # bisa dijawab langsung: berapa sesi yang terlambat, jam berapa orang biasanya
    # masuk, dan berapa lama sesinya.
    is_late = fields.Boolean(
        string='Late',
        compute='_compute_monitoring_fields',
        store=True,
    )
    late_session_count = fields.Integer(
        string='Late Sessions',
        compute='_compute_monitoring_fields',
        store=True,
        # `aggregator` membuat kolomnya bisa dipakai sebagai ukuran pivot dan
        # grafik; tanpa itu angkanya hanya bisa dibaca per baris.
        aggregator='sum',
        help='1 when the session was late, 0 otherwise. Summed in pivot and '
             'graph views to count late sessions.',
    )
    check_in_hour = fields.Float(
        string='Check-in Hour',
        compute='_compute_monitoring_fields',
        store=True,
        aggregator='avg',
        help='Hour of day the employee checked in, as a decimal, e.g. 7.5 for '
             '07:30. Averaged in pivot and graph views.',
    )
    session_hours = fields.Float(
        string='Session Hours',
        compute='_compute_monitoring_fields',
        store=True,
        digits=(6, 2),
        aggregator='sum',
        help='Length of the session, from check-in to check-out. Counted as 0 '
             'when either time is missing, when the shift ends before it starts '
             '(an overnight shift), or when the two are more than 24 hours apart '
             '— that last case means a check-out was missed, and counting it '
             'would inflate every total it appears in.',
    )

    @api.depends('late_minutes', 'check_in_time', 'check_out_time')
    def _compute_monitoring_fields(self):
        for log in self:
            log.is_late = bool(log.late_minutes and log.late_minutes > 0)
            log.late_session_count = 1 if log.is_late else 0
            log.check_in_hour = (
                log.check_in_time.hour + log.check_in_time.minute / 60.0
                if log.check_in_time else 0.0
            )
            if log.check_in_time and log.check_out_time:
                selisih = (log.check_out_time - log.check_in_time).total_seconds() / 3600.0
                # Dua keadaan dihitung 0, karena keduanya bukan lama kerja:
                # shift yang selesai sebelum mulai (lewat tengah malam), dan
                # selisih lebih dari 24 jam yang berarti check-out terlewat.
                # Angka seperti itu, kalau ikut dijumlahkan, menggelembungkan
                # total di pivot — lebih baik kosong daripada menyesatkan.
                log.session_hours = round(selisih, 2) if 0 < selisih <= 24 else 0.0
            else:
                log.session_hours = 0.0

    # ------------------------------------------------------------------
    # Kolom turunan untuk dibaca manusia
    # ------------------------------------------------------------------
    # Angka mentah dari server tetap disimpan apa adanya, tetapi di form angkanya
    # menyesatkan: "13587796.00" meter dan "250.00" meter adalah dua angka yang
    # harus dibandingkan sendiri oleh pembacanya, padahal jawabannya cuma satu
    # kata. Dua kolom per titik memisahkan fakta dari putusan: satu kalimat berisi
    # jarak dan radiusnya, satu putusan yang bisa disaring dan dikelompokkan.
    #
    # Disimpan (`store=True`) supaya bisa disaring dan dikelompokkan. Tanpa itu
    # pertanyaan "sesi mana yang di luar geofence" tidak bisa dijawab Odoo.
    check_in_distance_text = fields.Char(
        string='Check-in Distance',
        compute='_compute_geofence_texts',
        help='Distance from the office and the allowed radius, in units a person '
             'reads. Both numbers are the server\'s own; only the unit and the '
             'rounding are chosen here.',
    )
    check_in_radius_state = fields.Selection(
        string='Check-in Geofence',
        selection=[
            ('inside', 'Inside'),
            ('outside', 'Outside'),
            ('unknown', 'Unknown'),
        ],
        compute='_compute_geofence_states',
        store=True,
        help='Inside when the check-in point falls within the allowed radius. '
             'Unknown when either number is missing \u2014 being unknown is not the '
             'same as being outside.',
    )
    check_out_distance_text = fields.Char(
        string='Check-out Distance',
        compute='_compute_geofence_texts',
    )
    check_out_radius_state = fields.Selection(
        string='Check-out Geofence',
        selection=[
            ('inside', 'Inside'),
            ('outside', 'Outside'),
            ('unknown', 'Unknown'),
        ],
        compute='_compute_geofence_states',
        store=True,
    )
    late_text = fields.Char(
        string='Lateness',
        compute='_compute_late_text',
        help='Lateness as hours and minutes. The raw minute count stays in its '
             'own column for sums and pivots.',
    )
    session_text = fields.Char(
        string='Session Length',
        compute='_compute_session_text',
        help='Length of the session as hours and minutes. The raw hour count '
             'stays in its own column for sums and pivots.',
    )

    @staticmethod
    def _readable_distance(meters):
        """Jarak dalam satuan yang enak dibaca.

        Satuan ribuan memakai spasi, bukan titik atau koma: keduanya berarti hal
        berbeda di dua bahasa yang dipakai modul ini, jadi keduanya menyesatkan
        di salah satu bahasa. `m` dan `km` adalah satuan SI, jadi tidak perlu
        diterjemahkan.
        """
        if not meters or meters < 0:
            return ''
        if meters < 1000:
            return '%d m' % round(meters)
        kilometer = meters / 1000.0
        if kilometer < 10:
            return '%.1f km' % kilometer
        return '%s km' % '{:,.0f}'.format(kilometer).replace(',', '\u00a0')

    @classmethod
    def _distance_text(cls, distance, radius):
        """Kalimat fakta satu titik: jarak, lalu radius yang diizinkan."""
        teks = cls._readable_distance(distance)
        if not teks:
            return False
        radius_teks = cls._readable_distance(radius)
        if not radius_teks:
            return _('%s from the office', teks)
        return _('%s from the office, allowed %s', teks, radius_teks)

    @staticmethod
    def _radius_state(distance, radius):
        """Putusan geofence: di dalam, di luar, atau tidak diketahui."""
        if not distance or distance <= 0 or not radius or radius <= 0:
            return 'unknown'
        return 'inside' if distance <= radius else 'outside'

    @api.depends(
        'check_in_distance_meters', 'check_in_allowed_radius_meters',
        'check_out_distance_meters', 'check_out_allowed_radius_meters',
    )
    def _compute_geofence_states(self):
        """Putusan geofence. Disimpan supaya bisa disaring dan dikelompokkan.

        Sengaja tanpa `_()`: nilai kolomnya teknis (`inside`/`outside`), dan
        kolom tersimpan dihitung saat penulisan — termasuk oleh cron, yang tidak
        punya bahasa pengguna. Teks yang diterjemahkan dihitung saat dibaca, di
        `_compute_geofence_texts`.
        """
        for log in self:
            log.check_in_radius_state = self._radius_state(
                log.check_in_distance_meters, log.check_in_allowed_radius_meters
            )
            log.check_out_radius_state = self._radius_state(
                log.check_out_distance_meters, log.check_out_allowed_radius_meters
            )

    @api.depends(
        'check_in_distance_meters', 'check_in_allowed_radius_meters',
        'check_out_distance_meters', 'check_out_allowed_radius_meters',
    )
    def _compute_geofence_texts(self):
        """Kalimat jarak, dalam bahasa pembacanya.

        Tidak disimpan dengan sengaja. Kolom teks yang diterjemahkan lalu
        disimpan akan terbeku dalam bahasa yang berlaku saat kolom itu dihitung —
        dan cron menghitungnya tanpa bahasa pengguna sama sekali.
        """
        for log in self:
            log.check_in_distance_text = self._distance_text(
                log.check_in_distance_meters, log.check_in_allowed_radius_meters
            )
            log.check_out_distance_text = self._distance_text(
                log.check_out_distance_meters, log.check_out_allowed_radius_meters
            )

    @api.depends('late_minutes')
    def _compute_late_text(self):
        for log in self:
            menit = log.late_minutes or 0
            if menit <= 0:
                # Ditulis, bukan dikosongkan: baris kosong membuat pembaca menebak
                # apakah artinya tepat waktu atau datanya tidak ada.
                log.late_text = _('On time')
            elif menit < 60:
                log.late_text = _('%d min late', menit)
            else:
                log.late_text = _('%dh %dm late', menit // 60, menit % 60)

    @api.depends('session_hours')
    def _compute_session_text(self):
        for log in self:
            if not log.session_hours or log.session_hours <= 0:
                log.session_text = False
                continue
            # Dibulatkan ke menit lebih dulu, lalu dipecah: "0.88 jam" tidak bisa
            # dibaca, dan 0.88 jam bukan 53 menit kalau dibulatkan dua kali.
            menit = int(round(log.session_hours * 60))
            log.session_text = _('%dh %dm', menit // 60, menit % 60)

    @api.depends('employee_name', 'work_date')
    def _compute_display_name(self):
        for log in self:
            log.display_name = '%s - %s' % (log.employee_name or '?', log.work_date or '?')

    # ------------------------------------------------------------------
    # Penarikan
    # ------------------------------------------------------------------
    @api.model
    def _values_from_payload(self, company, row):
        """Petakan satu baris API ke kolom cermin."""
        if not isinstance(row, dict) or not row.get('id'):
            return None

        employee = row.get('employee') if isinstance(row.get('employee'), dict) else {}
        location = row.get('location') if isinstance(row.get('location'), dict) else {}
        shift = row.get('shift') if isinstance(row.get('shift'), dict) else {}
        in_mode = row.get('checkInMode') if isinstance(row.get('checkInMode'), dict) else {}
        out_mode = row.get('checkOutMode') if isinstance(row.get('checkOutMode'), dict) else {}
        tenant_client = location.get('tenantClient') if isinstance(location.get('tenantClient'), dict) else {}

        status = row.get('status')
        if status not in ('open', 'closed', 'alpha'):
            status = False

        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'session_key': row.get('session_key') or False,
            'work_date': row.get('work_date') or False,
            'user_id': int(row.get('user_id') or 0),
            'employee_name': employee.get('name') or False,
            'employee_nopeg': employee.get('nopeg') or False,
            'project_name': employee.get('project') or False,
            'location_id': int(row.get('location_id') or 0),
            'location_name': location.get('name') or False,
            'tenant_client_name': tenant_client.get('name') or False,
            'shift_id': int(row.get('shift_id') or 0),
            'shift_name': shift.get('shift_name') or False,
            'status': status,
            'late_minutes': int(row.get('late_minutes') or 0),
            'is_overtime': bool(row.get('is_overtime')),
            'check_in_time': parse_datetime(row.get('check_in_time')),
            'check_out_time': parse_datetime(row.get('check_out_time')),
            'check_in_latitude': float(row.get('check_in_latitude') or 0.0),
            'check_in_longitude': float(row.get('check_in_longitude') or 0.0),
            'check_in_distance_meters': float(row.get('check_in_distance_meters') or 0.0),
            'check_in_allowed_radius_meters': float(row.get('check_in_allowed_radius_meters') or 0.0),
            'check_in_mode_id': int(row.get('check_in_mode_id') or 0),
            'check_in_mode_name': in_mode.get('name') or False,
            'check_out_latitude': float(row.get('check_out_latitude') or 0.0),
            'check_out_longitude': float(row.get('check_out_longitude') or 0.0),
            'check_out_distance_meters': float(row.get('check_out_distance_meters') or 0.0),
            'check_out_allowed_radius_meters': float(row.get('check_out_allowed_radius_meters') or 0.0),
            'check_out_mode_id': int(row.get('check_out_mode_id') or 0),
            'check_out_mode_name': out_mode.get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }

    @api.model
    def _replace_scope(self, company, work_date_from, work_date_to):
        """Hapus cermin pada rentang tanggal sebelum menulis hasil tarikan baru.

        Mengganti per rentang, bukan menghapus semuanya, supaya penarikan satu
        bulan tidak menghapus bulan lain yang sudah ditarik sebelumnya.
        """
        domain = [('company_id', '=', company.id)]
        if work_date_from:
            domain.append(('work_date', '>=', work_date_from))
        if work_date_to:
            domain.append(('work_date', '<=', work_date_to))
        stale = self.sudo().search(domain)
        if stale:
            stale.unlink()
        return len(stale)

    @api.model
    def _upsert_rows(self, company, rows):
        Log = self.sudo()
        seen = set()
        written = 0
        for row in rows:
            values = self._values_from_payload(company, row)
            if not values:
                continue
            # Halaman bisa tumpang tindih bila data berubah di antara dua
            # permintaan. Dedupe menjaga jumlah yang dilaporkan tetap benar dan
            # mencegah penulisan berulang pada baris yang sama.
            key = values['external_id']
            if key in seen:
                continue
            seen.add(key)
            existing = Log.search([
                ('company_id', '=', company.id),
                ('external_id', '=', values['external_id']),
            ], limit=1)
            if existing:
                existing.write(values)
            else:
                Log.create(values)
            written += 1
        return written
