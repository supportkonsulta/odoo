"""Jadwal kerja mingguan: lokasi kerja dan shift per hari, per pegawai.

Presenly menyimpan pola mingguan, bukan penugasan per tanggal: satu baris untuk
setiap hari dalam sepekan, dengan lokasi kerja dan shiftnya, berlaku dalam rentang
`valid_from`–`valid_until`. Yang dipakai pegawai hari ini adalah baris hari ini.

Odoo tidak punya padanan untuk ini. `hr.employee.work_location_id` menunjuk satu
lokasi, dan itu diisi dari penempatan; jadwal hariannya tidak punya tempat. Jadi
polanya disimpan di cermin, dan di `hr.employee` ditampilkan sebagai daftar hari —
tanpa mengubah satu pun kolom native.

Baris yang hilang dari respons **dihapus**, berbeda dari pegawai yang tidak pernah
dihapus. Alasannya: daftar ini diambil utuh dalam sekali tarikan, jadi tidak adanya
sebuah baris berarti hari itu memang tidak dijadwalkan lagi — sedangkan jadwal basi
justru menyesatkan orang yang membacanya.
"""

import logging

from odoo import _, api, fields, models

from odoo.addons.presenly_saas.models.presenly_saas_config import redact
from odoo.addons.presenly_saas.services.saas_client import SaasClientError

_logger = logging.getLogger(__name__)

JADWAL_PATH = '/api/external/v1/weekly-schedules'
SLOT_PATH = '/api/external/v1/weekly-schedule-segments'

HARI = [
    ('mon', 'Monday'),
    ('tue', 'Tuesday'),
    ('wed', 'Wednesday'),
    ('thu', 'Thursday'),
    ('fri', 'Friday'),
    ('sat', 'Saturday'),
    ('sun', 'Sunday'),
]


class PresenlySaasEmployeeSchedule(models.Model):
    """Satu hari dalam pola mingguan seorang pegawai."""

    _name = 'presenly.saas.employee.schedule'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Employee Weekly Schedule (mirror)'
    _order = 'employee_nopeg, day_of_week, valid_from desc'
    _mirror_resource = 'weekly-schedules'

    name = fields.Char(compute='_compute_name', store=True)
    employee_nopeg = fields.Char(string='Nopeg', index=True)
    employee_name = fields.Char(string='Employee')

    day_of_week = fields.Selection(HARI, string='Day', index=True)
    is_workday = fields.Boolean(string='Working Day')
    slot_ids = fields.One2many(
        'presenly.saas.employee.slot', 'schedule_id', string='Slots', readonly=True,
    )
    slot_summary = fields.Char(
        string='Hours',
        compute='_compute_slot_summary', store=True,
        help='Start and end times of the slots on this day, taken from the slots '
             'themselves. Empty until the day has slots in Presenly — the shift '
             'alone does not tell when this person actually works.',
    )

    location_id = fields.Integer(
        string='Location ID', index=True,
        help='The work location id on the Presenly side. Dipakai untuk mencocokkan '
             'ke `hr.work.location` saat mengisi lokasi kerja biasa pegawai — '
             'mencocokkan lewat nama tidak bisa diandalkan karena nama bisa sama '
             'atau berubah.',
    )
    location_name = fields.Char(string='Work Location')
    shift_name = fields.Char(string='Shift')

    status = fields.Char(string='Status in Presenly')
    valid_from = fields.Date(string='Valid From')
    valid_until = fields.Date(string='Valid Until')

    hr_employee_id = fields.Many2one(
        'hr.employee',
        string='Odoo Employee',
        index=True,
        ondelete='cascade',
        help='Resolved from the nopeg, the same key the employee sync uses.',
    )

    @api.depends('slot_ids.start_time', 'slot_ids.end_time', 'slot_ids.sequence')
    def _compute_slot_summary(self):
        for row in self:
            bagian = [
                '%s\u2013%s' % (slot.start_time or '?', slot.end_time or '?')
                for slot in row.slot_ids.sorted('sequence')
            ]
            row.slot_summary = ', '.join(bagian)

    @api.depends('employee_name', 'day_of_week', 'location_name', 'shift_name')
    def _compute_name(self):
        label = dict(HARI)
        for row in self:
            bagian = [row.employee_name or row.employee_nopeg or _('Employee')]
            bagian.append(label.get(row.day_of_week, row.day_of_week or '?'))
            if not row.is_workday:
                bagian.append(_('not a working day'))
            elif row.location_name:
                bagian.append(row.location_name)
            if row.shift_name:
                bagian.append(row.shift_name)
            row.name = ' · '.join(bagian)


class PresenlySaasEmployeeSlot(models.Model):
    """Satu slot waktu di dalam satu hari pada pola mingguan.

    Jadwal mingguan menjawab "hari ini kerja di mana"; slot menjawab "jam berapa
    sampai jam berapa". Sebuah hari bisa punya beberapa slot, dan urutannya
    penting — itulah `sequence`.

    Hari, pegawai, dan lokasinya tidak dikirim di payload slot: yang dikirim hanya
    id jadwal induknya. Karena itu semuanya diambil dari baris jadwal yang sudah
    ada, bukan ditebak.
    """

    _name = 'presenly.saas.employee.slot'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Employee Weekly Slot (mirror)'
    _order = 'employee_nopeg, day_of_week, sequence'
    _mirror_resource = 'weekly-schedule-segments'

    name = fields.Char(compute='_compute_name', store=True)
    schedule_external_id = fields.Integer(
        string='Schedule ID', index=True,
        help='The weekly schedule row this slot belongs to, as Presenly numbers it.',
    )
    employee_nopeg = fields.Char(string='Nopeg', index=True)
    employee_name = fields.Char(string='Employee')
    day_of_week = fields.Selection(HARI, string='Day', index=True)

    sequence = fields.Integer(string='Slot', required=True, default=1)
    # Waktu disimpan sebagai teks apa adanya: di sisi server kolomnya bertipe TIME,
    # dan menafsirkannya ulang menjadi jam Odoo hanya menambah satu tempat yang
    # bisa salah tanpa menambah keterangan.
    start_time = fields.Char(string='Start')
    end_time = fields.Char(string='End')

    location_name = fields.Char(string='Work Location')
    shift_name = fields.Char(string='Shift')
    status = fields.Char(string='Status in Presenly')
    late_index = fields.Integer(
        string='Tolerance (min)',
        help='Minutes of lateness allowed on this slot. Empty means it follows the '
             'shift of that day, and then nought.',
    )

    schedule_id = fields.Many2one(
        'presenly.saas.employee.schedule',
        string='Weekly Schedule',
        index=True,
        ondelete='cascade',
        help='The weekly schedule row this slot belongs to. The slot payload only '
             'carries the schedule id, so the link is set at pull time.',
    )
    hr_employee_id = fields.Many2one(
        'hr.employee',
        string='Odoo Employee',
        index=True,
        ondelete='cascade',
        help='Resolved from the nopeg, the same key the employee sync uses.',
    )

    @api.depends('employee_name', 'day_of_week', 'sequence', 'start_time', 'end_time')
    def _compute_name(self):
        label = dict(HARI)
        for row in self:
            bagian = [
                row.employee_name or row.employee_nopeg or _('Employee'),
                label.get(row.day_of_week, row.day_of_week or '?'),
                _('slot %(n)s') % {'n': row.sequence or 1},
            ]
            if row.start_time or row.end_time:
                bagian.append('%s–%s' % (row.start_time or '?', row.end_time or '?'))
            row.name = ' · '.join(bagian)


class HrEmployee(models.Model):
    """Jadwal mingguan ditampilkan di pegawai native, tanpa kolom baru di sana."""

    _inherit = 'hr.employee'

    presenly_schedule_ids = fields.One2many(
        'presenly.saas.employee.schedule',
        'hr_employee_id',
        string='Work Location by Day',
        readonly=True,
    )
    presenly_slot_ids = fields.One2many(
        'presenly.saas.employee.slot',
        'hr_employee_id',
        string='Work Slots',
        readonly=True,
    )

    presenly_uses_slots = fields.Boolean(
        string='Uses Slot Schedule',
        compute='_compute_presenly_uses_slots',
        help='True when any day of this employee has slots. The mode is inferred '
             'from the data, not stored: a stored choice can disagree with what is '
             'actually filled in, and then nobody knows which one is right.',
    )

    @api.depends('presenly_slot_ids')
    def _compute_presenly_uses_slots(self):
        for pegawai in self:
            pegawai.presenly_uses_slots = bool(pegawai.presenly_slot_ids)


class PresenlySaasConfig(models.Model):
    """Penarikan jadwal mingguan."""

    _inherit = 'presenly.saas.config'

    def _pull_employees(self):
        """Setelah pegawai ditarik, jadwalnya menyusul.

        Dipanggil di sini karena jadwal menunjuk ke pegawai lewat nopeg; pegawai
        itu baru ada setelah tarikan sebelumnya.
        """
        ringkas, error = super()._pull_employees()
        if error:
            return ringkas, error

        ringkas_jadwal, error_jadwal = self._pull_schedules()
        if error_jadwal:
            return ringkas, error_jadwal
        ringkas['schedules'] = ringkas_jadwal

        ringkas_slot, error_slot = self._pull_slots()
        if error_slot:
            return ringkas, error_slot
        ringkas['slots'] = ringkas_slot

        # Dijalankan paling akhir, setelah penempatan: penempatan tetap yang utama,
        # dan yang diisi di sini hanya yang masih kosong.
        ringkas['usual_locations'] = self._fill_usual_locations()
        return ringkas, error

    def _pull_slots(self):
        """Selaraskan slot waktu. Mengembalikan ``(ringkasan, error)``.

        Hari, pegawai, dan lokasinya diambil dari baris jadwal induknya: payload
        slot hanya membawa id jadwalnya, bukan isinya.
        """
        self.ensure_one()
        started = fields.Datetime.now()
        try:
            rows, _meta, _pages = self._fetch_pages(
                lambda params, _client=self._client().get_resource:
                    _client('weekly-schedule-segments', params),
                {'limit': 500},
            )
        except SaasClientError as exc:
            self._log_pull(SLOT_PATH, False, exc, started)
            return {}, redact(exc, self.api_key)

        Cermin = self.env['presenly.saas.employee.slot'].sudo()
        Jadwal = self.env['presenly.saas.employee.schedule'].sudo()

        ringkasan = {'created': 0, 'updated': 0, 'removed': 0, 'without_schedule': 0}
        terlihat = set()
        jadwal_terlihat = set()

        for row in rows:
            if not isinstance(row, dict) or not row.get('id'):
                continue
            # Slot yang dibatalkan juga riwayat, dan diperlakukan sama.
            if (row.get('status') or 'active') != 'active':
                continue
            external_id = int(row['id'])
            terlihat.add(external_id)

            induk = row.get('weekly_schedule') if isinstance(row.get('weekly_schedule'), dict) else {}
            induk_id = int((induk or {}).get('id') or 0)
            if induk_id:
                jadwal_terlihat.add(induk_id)

            jadwal = Jadwal.search([
                ('company_id', '=', self.company_id.id), ('external_id', '=', induk_id),
            ], limit=1) if induk_id else Jadwal.browse()
            if induk_id and not jadwal:
                ringkasan['without_schedule'] += 1

            tempat = row.get('location') if isinstance(row.get('location'), dict) else {}
            shift = row.get('shift') if isinstance(row.get('shift'), dict) else {}

            nilai = {
                'company_id': self.company_id.id,
                'external_id': external_id,
                'schedule_external_id': induk_id,
                'employee_nopeg': jadwal.employee_nopeg or False,
                'employee_name': jadwal.employee_name or False,
                'day_of_week': jadwal.day_of_week or False,
                'sequence': int(row.get('sequence') or 1),
                'start_time': row.get('start_time') or False,
                'end_time': row.get('end_time') or False,
                'location_name': (tempat or {}).get('name') or jadwal.location_name or False,
                'shift_name': (shift or {}).get('name') or jadwal.shift_name or False,
                'status': row.get('status') or False,
                'hr_employee_id': jadwal.hr_employee_id.id or False,
                'schedule_id': jadwal.id or False,
                'late_index': row.get('late_index') if row.get('late_index') is not None else False,
            }

            cermin = Cermin.search([
                ('company_id', '=', self.company_id.id), ('external_id', '=', external_id),
            ], limit=1)
            if cermin:
                cermin.write(nilai)
                ringkasan['updated'] += 1
            else:
                Cermin.create(nilai)
                ringkasan['created'] += 1

            # Kalau satu hari dipecah beberapa slot, jadwal hariannya sendiri tidak
            # membawa lokasi dan shift — keduanya ada di slotnya. Barisnya diisi
            # dari slot pertama supaya daftar hariannya tidak tampil kosong di
            # kolom yang justru paling sering dilihat. Yang sudah ada tidak
            # ditimpa: itu isi kiriman server apa adanya.
            if jadwal and (not jadwal.location_name or not jadwal.shift_name):
                isi = {}
                if not jadwal.location_name and nilai['location_name']:
                    isi['location_name'] = nilai['location_name']
                if not jadwal.shift_name and nilai['shift_name']:
                    isi['shift_name'] = nilai['shift_name']
                if isi:
                    jadwal.write(isi)

        # Sama seperti jadwal: yang hilang dari respons memang hilang, tetapi hanya
        # untuk jadwal yang muncul di respons ini — tarikan yang terpotong tidak
        # boleh menghapus slot milik jadwal yang tidak terlihat.
        if jadwal_terlihat:
            hilang = Cermin.search([
                ('company_id', '=', self.company_id.id),
                ('schedule_external_id', 'in', list(jadwal_terlihat)),
                ('external_id', 'not in', list(terlihat)),
            ])
            ringkasan['removed'] = len(hilang)
            if hilang:
                hilang.unlink()

        self._log_pull(SLOT_PATH, True, None, started)
        _logger.info(
            'Presenly SaaS: slot jadwal diselaraskan (%s baru, %s diperbarui, %s '
            'dihapus, %s tanpa jadwal).',
            ringkasan['created'], ringkasan['updated'], ringkasan['removed'],
            ringkasan['without_schedule'],
        )
        return ringkasan, False

    def _fill_usual_locations(self):
        """Isi lokasi kerja biasa pegawai dari polanya, kalau penempatan tidak memberi.

        Penempatan tetap yang utama: kalau ia sudah menunjuk lokasi, tidak ada yang
        disentuh di sini. Yang diisi hanya yang kosong — dan itu keadaan nyata:
        pegawai yang belum ditempatkan tetap punya pola kerja.

        Yang dipakai adalah lokasi yang **paling sering muncul di hari kerjanya**,
        bukan lokasi hari pertama: pola kerja bisa berbeda-beda antar hari, dan
        yang mewakili "biasanya" adalah yang terbanyak. Seri diputus oleh id
        terkecil supaya hasilnya sama di setiap tarikan.
        """
        self.ensure_one()
        if not self.fill_usual_location:
            # Mati secara bawaan: lokasi kerja biasa milik penempatan, dan pola
            # kerja hanya cadangan. Menyalakannya adalah keputusan.
            return {'filled': 0, 'no_schedule': 0, 'no_location': 0, 'off': True}

        Hr = self.env['hr.employee'].sudo().with_context(active_test=False)
        Cermin = self.env['presenly.saas.employee.schedule'].sudo()
        Lokasi = self.env['hr.work.location'].sudo().with_context(active_test=False)

        ringkasan = {'filled': 0, 'no_schedule': 0, 'no_location': 0}
        kosong = Hr.search([
            ('presenly_nopeg', '!=', False), ('work_location_id', '=', False),
        ])
        for hr in kosong:
            baris = Cermin.search([
                ('company_id', '=', self.company_id.id),
                ('employee_nopeg', '=', hr.presenly_nopeg),
                ('status', '=', 'active'),
                ('is_workday', '=', True),
                ('location_id', '!=', 0),
            ])
            if not baris:
                ringkasan['no_schedule'] += 1
                continue
            hitung = {}
            for b in baris:
                hitung[b.location_id] = hitung.get(b.location_id, 0) + 1
            terpilih = sorted(hitung.items(), key=lambda x: (-x[1], x[0]))[0][0]
            lokasi = Lokasi.search([('presenly_external_id', '=', terpilih)], limit=1)
            if not lokasi:
                ringkasan['no_location'] += 1
                continue
            # Penanda anti-echo: ini tulisan sinkronisasi, bukan suntingan pengguna.
            hr.with_context(presenly_skip_push=True).write({'work_location_id': lokasi.id})
            ringkasan['filled'] += 1

        if ringkasan['filled'] or ringkasan['no_location']:
            _logger.info(
                'Presenly SaaS: lokasi kerja biasa diisi dari pola kerja (%s diisi, '
                '%s tanpa pola, %s lokasinya belum ada di Odoo).',
                ringkasan['filled'], ringkasan['no_schedule'], ringkasan['no_location'],
            )
        return ringkasan

    fill_usual_location = fields.Boolean(
        string='Fill Usual Work Location from the Pattern',
        default=False,
        help='When an employee has no work location from their placement, take it '
             'from the location they work at most often in their weekly pattern. '
             'Off by default: the placement owns that field.',
    )

    def _pull_schedules(self):
        """Selaraskan pola mingguan. Mengembalikan ``(ringkasan, error)``."""
        self.ensure_one()
        started = fields.Datetime.now()
        try:
            rows, _meta, _pages = self._fetch_pages(
                lambda params, _client=self._client().get_resource:
                    _client('weekly-schedules', params),
                {'limit': 500},
            )
        except SaasClientError as exc:
            self._log_pull(JADWAL_PATH, False, exc, started)
            return {}, redact(exc, self.api_key)

        Cermin = self.env['presenly.saas.employee.schedule'].sudo()
        Hr = self.env['hr.employee'].sudo().with_context(active_test=False)

        terdahulu = {}
        ringkasan = {'created': 0, 'updated': 0, 'removed': 0, 'without_employee': 0}
        terlihat = set()
        pegawai_terlihat = set()

        for row in rows:
            if not isinstance(row, dict) or not row.get('id'):
                continue
            # Pola lama tidak disimpan. Aplikasi menyimpan riwayatnya — setiap
            # perubahan meninggalkan baris `inactive` — dan di sini riwayat itu
            # hanya membuat daftarnya terlihat seperti duplikat: tujuh hari
            # menjadi puluhan baris untuk satu pegawai. Kalau suatu saat riwayatnya
            # diperlukan, sumbernya tetap ada di aplikasi.
            if (row.get('status') or 'active') != 'active':
                terdahulu['dilewati'] = terdahulu.get('dilewati', 0) + 1
                continue
            external_id = int(row['id'])
            terlihat.add(external_id)

            pegawai = row.get('employee') if isinstance(row.get('employee'), dict) else {}
            nopeg = (pegawai or {}).get('nopeg') or False
            if nopeg:
                pegawai_terlihat.add(nopeg)

            tempat = row.get('location') if isinstance(row.get('location'), dict) else {}
            shift = row.get('shift') if isinstance(row.get('shift'), dict) else {}

            nilai = {
                'company_id': self.company_id.id,
                'external_id': external_id,
                'employee_nopeg': nopeg,
                'employee_name': (pegawai or {}).get('name') or False,
                'day_of_week': row.get('day_of_week') or False,
                'is_workday': bool(row.get('is_workday')),
                'location_id': int((tempat or {}).get('id') or 0),
            'location_name': (tempat or {}).get('name') or False,
                'shift_name': (shift or {}).get('name') or False,
                'status': row.get('status') or False,
                'valid_from': row.get('valid_from') or False,
                'valid_until': row.get('valid_until') or False,
            }

            hr = Hr.search([('presenly_nopeg', '=', nopeg)], limit=1) if nopeg else Hr.browse()
            nilai['hr_employee_id'] = hr.id or False
            if nopeg and not hr:
                ringkasan['without_employee'] += 1

            cermin = Cermin.search([
                ('company_id', '=', self.company_id.id), ('external_id', '=', external_id),
            ], limit=1)
            if cermin:
                cermin.write(nilai)
                ringkasan['updated'] += 1
            else:
                Cermin.create(nilai)
                ringkasan['created'] += 1

        # Baris yang hilang dari respons dihapus — tetapi hanya milik pegawai yang
        # memang muncul di respons ini. Kalau tarikannya terpotong, pegawai yang
        # tidak terlihat jangan ikut kehilangan jadwalnya.
        if pegawai_terlihat:
            hilang = Cermin.search([
                ('company_id', '=', self.company_id.id),
                ('employee_nopeg', 'in', list(pegawai_terlihat)),
                ('external_id', 'not in', list(terlihat)),
            ])
            ringkasan['removed'] = len(hilang)
            if hilang:
                hilang.unlink()

        ringkasan['skipped'] = terdahulu.get('dilewati', 0)
        self._log_pull(JADWAL_PATH, True, None, started)
        _logger.info(
            'Presenly SaaS: jadwal mingguan diselaraskan (%s baru, %s diperbarui, '
            '%s dihapus, %s tanpa pegawai).',
            ringkasan['created'], ringkasan['updated'], ringkasan['removed'],
            ringkasan['without_employee'],
        )
        return ringkasan, False
