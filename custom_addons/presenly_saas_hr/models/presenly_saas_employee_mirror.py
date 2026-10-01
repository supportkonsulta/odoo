import logging

from odoo import _, api, fields, models

from odoo.addons.presenly_saas.models.presenly_saas_attendance_log import parse_datetime
from odoo.addons.presenly_saas.models.presenly_saas_payload import parse_date, person_ref
from odoo.addons.presenly_saas.services.saas_client import SaasClientError

_logger = logging.getLogger(__name__)


class PresenlySaasEmployee(models.Model):
    """Cermin `GET /v1/employees`, sekaligus jembatan ke `hr.employee`.

    Cermin ini menyimpan **seluruh** payload apa adanya. `hr.employee` hanya
    menerima kolom yang punya padanan di sana. Pemisahan ini disengaja: kolom
    seperti `bagian`, `grup`, `can_approve`, dan PII tidak punya rumah di Odoo,
    dan menebak rumahnya berisiko merusak data kepegawaian yang sudah ada.

    Arah sinkronisasi saat ini **satu arah**: Presenly -> Odoo. Arah sebaliknya
    menunggu endpoint tulis di sisi server. Rinciannya di `PLAN_HR_SYNC.md`.
    """

    _name = 'presenly.saas.employee'
    _inherit = ['presenly.saas.mirror.mixin']
    _description = 'Presenly Employee (mirror)'
    _order = 'name'

    _mirror_resource = 'employees'

    nopeg = fields.Char(string='Nopeg', index=True)
    name = fields.Char(required=True)
    email = fields.Char()
    phone = fields.Char()
    is_active = fields.Boolean(string='Active in Presenly')

    # Kolom yang tidak punya padanan di Odoo. Disimpan di sini supaya tidak ada
    # informasi yang hilang, dan supaya bisa dilihat saat memutuskan pemetaan.
    bagian = fields.Char()
    grup = fields.Char(string='Grup')
    address = fields.Text()
    birth_date = fields.Date(string='Birth Date')
    birth_place = fields.Char(string='Birth Place')
    can_approve = fields.Boolean(string='Can Approve')
    # Hak menyetujui yang **efektif** — dihitung server, bukan flag tersimpan.
    # Flag tersimpan bisa nol untuk orang yang justru approver di alurnya.
    can_approve_effective = fields.Boolean(string='May Approve')
    role_name = fields.Char(string='Role')

    # Atasan langsung, apa adanya dari payload. Inilah yang membuat level
    # persetujuan bertipe `direct_manager` bisa dicocokkan ke pengguna Odoo:
    # server tidak mengirim siapa atasannya (bergantung pemohon), tetapi tiap
    # pegawai membawa atasannya sendiri.
    manager_nopeg = fields.Char(string='Manager Nopeg', index=True)
    manager_name = fields.Char(string='Manager')

    shift_name = fields.Char(string='Shift')

    # Presenly menamai ini `internal_company`; di sini sebutannya **cabang**,
    # karena itulah pertanyaan yang dijawab kolom ini: pegawai ini bernaung di
    # cabang mana. Angka `id`-nya adalah id klien di sisi Presenly, dan kolom
    # nama sengaja terpisah supaya tetap terbaca walau perusahaan Odoo dengan
    # id itu belum pernah dibuat.
    internal_company_id = fields.Integer(string='Branch Client ID', index=True)
    branch_ids = fields.Many2many(
        'res.company',
        related='hr_employee_id.presenly_client_ids',
        string='Branches',
        readonly=True,
        help='Branches that are actually in effect, taken from the placements of '
             'the Odoo employee this row is linked to. The employee payload only '
             'ever carries one client, so this is where the full picture is. Left '
             'as a related field on purpose: the list lives in one place, not two.',
    )
    internal_company_name = fields.Char(
        string='Branch',
        help='Which branch this employee works for, as reported by Presenly. '
             'Empty when Presenly does not name one on the employee itself; the '
             'placements carry the branches, one row per employee and client, and '
             'those are not stored here yet.',
    )

    # PII — NPWP, rekening, dan BPJS — tidak disimpan di sini. Odoo HR tidak
    # membutuhkannya, dan setiap salinan adalah satu tempat lagi yang harus
    # dijaga kerahasiaannya. Datanya tetap di aplikasi Presenly, di sana ia
    # memang berada.

    hr_employee_id = fields.Many2one(
        'hr.employee',
        string='Odoo Employee',
        readonly=True,
        ondelete='set null',
        help='The Odoo employee record this row is linked to.',
    )

    synced_state = fields.Selection(
        selection=[
            ('linked', 'Linked'),
            ('unlinked', 'Not Linked'),
            ('no_nopeg', 'No Nopeg'),
        ],
        compute='_compute_synced_state',
        string='Sync',
    )

    @api.depends('hr_employee_id', 'nopeg')
    def _compute_synced_state(self):
        for row in self:
            if not row.nopeg:
                row.synced_state = 'no_nopeg'
            elif row.hr_employee_id:
                row.synced_state = 'linked'
            else:
                row.synced_state = 'unlinked'

    @api.depends('name', 'nopeg')
    def _compute_display_name(self):
        for employee in self:
            employee.display_name = '%s (%s)' % (
                employee.name or '?', employee.nopeg or 'no nopeg',
            )

    @api.model
    def _mirror_values(self, company, row):
        if not isinstance(row, dict) or not row.get('id'):
            return None
        role = row.get('role')
        manager = row.get('manager')
        shift = row.get('shift')
        internal_company = row.get('internal_company')
        if not isinstance(internal_company, dict):
            internal_company = {}
        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'nopeg': row.get('nopeg') or False,
            'name': row.get('name') or '',
            'email': row.get('email') or False,
            'phone': row.get('phone') or False,
            'is_active': bool(row.get('is_active')),
            'bagian': row.get('bagian') or False,
            'grup': row.get('grup') or False,
            'address': row.get('address') or False,
            'birth_date': parse_date(row.get('birth_date')),
            'birth_place': row.get('birth_place') or False,
            'can_approve': bool(row.get('can_approve')),
            'can_approve_effective': bool(row.get('can_approve_effective')),
            'role_name': (role.get('name') if isinstance(role, dict) else None) or False,
            'manager_nopeg': (manager.get('nopeg') if isinstance(manager, dict) else None) or False,
            'manager_name': (manager.get('name') if isinstance(manager, dict) else None) or False,
            'shift_name': (shift.get('name') if isinstance(shift, dict) else None) or False,
            # Cabang ditulis apa adanya dari Presenly, tanpa cadangan ke
            # perusahaan utama. Sebelumnya ada cadangan begitu, dan itu keliru:
            # perusahaan utama bukan cabang, dan mengisinya membuat laporan
            # cabang terlihat lengkap padahal datanya tidak ada. Cabang yang
            # sebenarnya ada di resource `placements`, satu baris per
            # pegawai-dan-klien; pengisian dari sana belum dikerjakan.
            'internal_company_id': int(internal_company.get('id') or 0),
            'internal_company_name': internal_company.get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }

    @api.model
    def _upsert_rows(self, company, rows):
        """Tulis per `external_id`, tanpa menghapus baris yang tidak disebut.

        Berbeda dari cermin referensi yang mengganti seluruh isi. Pegawai tidak
        pernah dihapus, baik di cermin maupun di `hr.employee`: menghapus baris
        pegawai berdasarkan hasil satu tarikan berisiko menghapus data
        kepegawaian yang masih dipakai.
        """
        Mirror = self.sudo()
        seen = set()
        written = 0
        for row in rows:
            values = self._mirror_values(company, row)
            if not values:
                continue
            key = values['external_id']
            if key in seen:
                continue
            seen.add(key)
            existing = Mirror.search([
                ('company_id', '=', company.id),
                ('external_id', '=', key),
            ], limit=1)
            if existing:
                existing.write(values)
            else:
                Mirror.create(values)
            written += 1
        return written

    # ------------------------------------------------------------------
    # Sinkronisasi ke hr.employee
    # ------------------------------------------------------------------
    # Kolom yang dibandingkan di kedua sisi. Isinya kolom yang dikirim balik
    # ditambah `is_active`, yang dimiliki Presenly tetapi tetap perlu
    # dibandingkan supaya perubahannya ikut diterapkan.
    SHARED_FIELDS = ('name', 'email', 'phone', 'birth_date', 'birth_place',
                     'address', 'is_active',
                     # `bagian` dipetakan ke jabatan. Ikut dibandingkan supaya
                     # pegawai yang sudah tersinkron pun mendapat jabatannya.
                     #
                     # `internal_company_id` TIDAK ikut: sisi Odoo selalu punya
                     # perusahaan (bawaan pemasangan), sedangkan klien di Presenly
                     # boleh kosong. Membandingkannya membuat setiap tarikan
                     # terlihat bentrok, dan pegawai yang bentrok tidak dikirim
                     # balik — pengiriman yang sah jadi ikut hilang.
                     # Kolom yang tadinya hanya ada di cermin, kini punya rumah
                     # di `hr.employee`. Ruang nilainya sama dengan cermin, jadi
                     # ikut dibandingkan dan bentroknya ikut dilaporkan.
                     'bagian', 'grup', 'can_approve', 'can_approve_effective',
                     'role_name', 'shift_name')

    # Kolom milik Presenly yang **tidak** dikirim balik. Perubahannya tetap
    # dilaporkan kalau Odoo juga menyentuhnya, karena nilainya akan tertimpa —
    # dan suntingan yang hilang tanpa jejak persis yang dihindari modul ini.
    MILIK_PRESENLY = ('grup', 'can_approve', 'role_name', 'shift_name')

    # Kolom yang dikirim BALIK ke Presenly. `is_active` sengaja tidak ada di
    # sini: status aktif dimiliki Presenly, dan Odoo tidak pernah menulisnya.
    # Kalau ikut dikirim, menonaktifkan pegawai di Odoo akan mencabut aksesnya
    # di aplikasi Presenly — persis kebalikan dari penjagaan di sisi seberang.
    PUSH_FIELDS = ('name', 'email', 'phone', 'birth_date', 'birth_place', 'address')

    PUSH_TO_HR_FIELD = {
        'name': 'name',
        'email': 'work_email',
        'phone': 'work_phone',
        'birth_date': 'birthday',
        'birth_place': 'place_of_birth',
        'address': 'private_street',
        # Ikut dibandingkan supaya perubahan status aktif ikut diterapkan,
        # tetapi TIDAK ikut dikirim balik (lihat `PUSH_FIELDS`).
        'is_active': 'active',
        # Dipakai untuk menautkan, bukan untuk dikirim balik: `bagian` menjadi
        # jabatan. Klien Presenly juga menjadi perusahaan Odoo, tetapi tautan itu
        # diterapkan lewat `_hr_values` tanpa ikut dibandingkan (lihat
        # `SHARED_FIELDS`).
        'bagian': 'job_title',
        'grup': 'presenly_group',
        'can_approve': 'presenly_can_approve',
        'can_approve_effective': 'presenly_may_approve',
        'role_name': 'presenly_role',
        'shift_name': 'presenly_shift',
    }

    @api.model
    def _hr_values(self, employee):
        """Kolom `hr.employee` yang boleh ditulis dari payload Presenly.

        Hanya berisi kolom yang **ada di kedua sisi**. Sisanya sengaja tidak
        dipetakan; alasannya di `PLAN_HR_SYNC.md` §3.
        """
        nilai = {
            'name': employee.name,
            'work_email': employee.email or False,
            'work_phone': employee.phone or False,
            'birthday': employee.birth_date or False,
            'place_of_birth': employee.birth_place or False,
            'private_street': employee.address or False,
            # `bagian` di Presenly berisi nama jabatan (mis. "IT Engineer"),
            # bukan nama bagian organisasi. Padanan Odoo yang artinya sama
            # adalah `job_title`, sedangkan `department_id` menuntut data
            # organisasi yang belum dikirim server.
            'job_title': employee.bagian or False,
        }

        # Pegawai berada di perusahaan tempat integrasi dipasang, dan kliennya
        # disimpan sebagai kolom tersendiri.
        #
        # Sebelumnya klien dijadikan perusahaan pegawai, dan akibatnya daftar
        # pegawai Odoo terpencar ke perusahaan-perusahaan klien: dengan pemilih
        # perusahaan di posisi satu perusahaan, sebagian besar pegawai tidak
        # terlihat — dan itu terbaca sebagai "tarikannya gagal", padahal datanya
        # ada. Menyatukannya di satu perusahaan membuat daftarnya utuh, tanpa
        # kehilangan keterangan kliennya.
        nilai['company_id'] = employee.company_id.id
        # Klien ditulis hanya bila payload pegawai memang membawanya. Sebagian
        # besar tidak membawanya — klien datang dari penempatan — dan menulis
        # kosong di sini akan menghapus nilai yang baru saja diisi penempatan.
        if employee.internal_company_id:
            nilai['presenly_client_id'] = employee.internal_company_id
            nilai['presenly_client_name'] = employee.internal_company_name or False

        # Atasan dicari lewat nopeg, kunci yang sama dengan penautan pegawai.
        # Kalau atasannya belum tertaut di Odoo, dibiarkan kosong dan keadaannya
        # terlihat dari cermin — menebak dari nama akan salah orang.
        #
        # Kolom yang tidak punya padanan native di Odoo. Disimpan apa adanya:
        # `role` sengaja BUKAN grup Odoo — kalau peran di aplikasi menjadi hak
        # akses di sini, satu perubahan di sana bisa memberi orang izin yang tidak
        # pernah disetujui siapa pun di Odoo.
        nilai['presenly_group'] = employee.grup or False
        nilai['presenly_can_approve'] = bool(employee.can_approve)
        nilai['presenly_may_approve'] = bool(employee.can_approve_effective)
        nilai['presenly_role'] = employee.role_name or False
        nilai['presenly_shift'] = employee.shift_name or False

        # PII tidak disalin ke `hr.employee`. Nomor NPWP, rekening, dan BPJS tetap
        # ada di aplikasi; Odoo HR tidak membutuhkannya, dan menaruhnya di sini
        # berarti satu lagi tempat yang harus dijaga kerahasiaannya.

        atasan = self._hr_oleh_nopeg(employee.manager_nopeg)
        if atasan:
            # Id, karena inilah bentuk yang ditulis ke database. Pembandingnya
            # yang menyesuaikan diri — lihat `_beda_nilai`.
            nilai['parent_id'] = atasan.id
        return nilai

    @api.model
    def _hr_oleh_nopeg(self, nopeg):
        """Pegawai Odoo yang memegang nopeg ini, kalau ada."""
        if not nopeg:
            return self.env['hr.employee'].browse()
        return self._hr_model().sudo().with_context(active_test=False).search(
            [('presenly_nopeg', '=', nopeg)], limit=1
        )

    @api.model
    def _presenly_company(self, client_id):
        """Perusahaan Odoo yang mencerminkan klien Presenly itu, kalau ada."""
        if not client_id:
            return self.env['res.company'].browse()
        return self.env['res.company'].sudo().search(
            [('presenly_client_id', '=', client_id)], limit=1
        )

    def _hr_model(self):
        """Model `hr.employee` dengan penanda agar tidak memicu kirim balik.

        Sinkronisasi menulis ke model yang sama dengan yang dipakai pengguna.
        Tanpa penanda ini, setiap penulisan dari tarikan akan mengantrekan
        pengiriman balik ke Presenly — termasuk nilai yang baru saja diterima
        dari sana, sehingga berputar tanpa henti.
        """
        return self.env['hr.employee'].with_context(presenly_skip_push=True)

    @api.model
    def _cari_hr_employee(self, nopeg):
        """Cari `hr.employee` yang sudah bertaut ke nopeg ini.

        Mengembalikan `(record, ganda)`. `ganda` bernilai True bila ada lebih
        dari satu. Nopeg ganda tidak dipilihkan salah satu: salah pilih berarti
        menulis data ke pegawai yang salah, dan itu lebih buruk daripada berhenti
        lalu melaporkannya.
        """
        Hr = self._hr_model().sudo().with_context(active_test=False)
        matches = Hr.search([('presenly_nopeg', '=', nopeg)])
        if len(matches) > 1:
            return self.env['hr.employee'], True
        return matches, False

    def _link_hr_employee(self, employee=None):
        """Pasangkan baris cermin dengan `hr.employee` lewat nopeg.

        Mengembalikan `(recordset_hr, dibuat)`. Recordset kosong berarti barisnya
        tidak bisa dipasangkan.
        """
        records = (employee or self).sudo()
        hasil = self.env['hr.employee']
        dibuat = False
        for row in records:
            if not row.nopeg:
                # Tanpa nopeg tidak ada kunci penghubung. Membuat pegawai baru
                # hanya akan menghasilkan duplikat yang tidak bisa dicocokkan
                # lagi di tarikan berikutnya.
                continue
            existing, ganda = self._cari_hr_employee(row.nopeg)
            if ganda:
                continue
            if existing:
                row.hr_employee_id = existing.id
                hasil |= existing
                continue
            values = self._hr_values(row)
            values['presenly_nopeg'] = row.nopeg
            # `active` tidak ikut saat pembuatan: pegawai baru selalu aktif,
            # dan `is_active` dari Presenly ditangani di `_sync_to_hr` supaya
            # satu aturan saja yang berlaku.
            baru = self._hr_model().sudo().create(values)
            row.hr_employee_id = baru.id
            hasil |= baru
            dibuat = True
        return hasil, dibuat

    @api.model
    def _sync_to_hr(self, company):
        """Terapkan isi cermin ke `hr.employee`.

        Mengembalikan ringkasan berisi jumlah yang dibuat, diperbarui,
        dilewati, dan **ditolak** beserta alasannya. Yang ditolak dilaporkan,
        tidak diam-diam diabaikan.
        """
        Mirror = self.sudo()
        rows = Mirror.search([('company_id', '=', company.id)])
        summary = {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': [],
                   'refused': [], 'conflicts': []}

        for row in rows:
            if not row.nopeg:
                summary['skipped'].append(
                    _('%(name)s: no nopeg, so there is no key to link on.',
                      name=row.name or row.external_id)
                )
                continue

            hr = row.hr_employee_id
            if not hr:
                _existing, ganda = row._cari_hr_employee(row.nopeg)
                if ganda:
                    summary['skipped'].append(
                        _('%(name)s (nopeg %(nopeg)s): more than one Odoo employee '
                          'carries this nopeg, so none was touched.',
                          name=row.name or row.external_id, nopeg=row.nopeg)
                    )
                    continue
                hr, dibuat = row._link_hr_employee()
                if not hr:
                    summary['skipped'].append(
                        _('%(name)s: could not be linked to an Odoo employee.',
                          name=row.name or row.external_id)
                    )
                    continue
                if dibuat:
                    # Sudah dibuat lengkap oleh `create`, jadi tidak perlu
                    # dihitung sebagai "diperbarui" juga.
                    summary['created'] += 1
                    self._apply_active(row, hr, summary)
                    row.hr_employee_id = hr.id
                    self._stamp_synced(row, hr)
                    continue

            # Yang dibandingkan adalah NILAI di kedua sisi terhadap snapshot
            # terakhir, bukan `updated_at`. Jam dua server tidak bisa
            # dibandingkan dengan andal, dan `updated_at` bisa saja tidak
            # berubah walaupun isinya berubah — perubahan seperti itu akan
            # terlewat tanpa jejak.
            snapshot = hr.presenly_synced_values or {}
            presenly_beda = self._beda(
                self._mirror_values_for(row, self.SHARED_FIELDS), snapshot
            )
            # Atasan tidak ada di `SHARED_FIELDS` karena ruang nilainya berbeda:
            # cermin menyimpan nopeg, Odoo menyimpan id pegawai. Karena itu
            # diperiksa terpisah — tanpa ini, perubahan atasan saja tidak pernah
            # diterapkan, dan kelalaian seperti itu sulit terlihat.
            if (snapshot.get('manager_nopeg') or '') != (row.manager_nopeg or ''):
                presenly_beda['manager_nopeg'] = row.manager_nopeg or False
                # Kalau atasan juga diubah di Odoo, yang di Odoo akan tertimpa.
                # Itu diperlakukan sama dengan bentrok kolom lain: dilaporkan,
                # bukan dihilangkan diam-diam.
                if (snapshot.get('manager_nopeg') or '') and \
                        (hr.parent_id.presenly_nopeg or '') not in ('', snapshot.get('manager_nopeg')):
                    summary['conflicts'].append(
                        _('%(name)s (nopeg %(nopeg)s): the manager was changed on both '
                          'sides; the Presenly value was kept.',
                          name=hr.name or row.name, nopeg=row.nopeg)
                    )

            # Bila Presenly tidak berubah, suntingan yang dibuat di Odoo harus
            # dibiarkan utuh supaya bisa dikirim balik oleh `_push_to_presenly`.
            # Menimpanya di sini akan menghapusnya sebelum sempat terkirim.
            if not presenly_beda:
                summary['unchanged'] += 1
                row.hr_employee_id = hr.id
                continue

            # Presenly berubah. Kalau Odoo juga berubah sejak sinkronisasi
            # terakhir, tidak ada cara andal untuk tahu mana yang lebih baru.
            # Presenly menang karena ia sistem kepegawaian yang sebenarnya, dan
            # bentroknya dilaporkan supaya suntingan Odoo tidak hilang diam-diam.
            if self._changed_fields(hr):
                summary['conflicts'].append(
                    _('%(name)s (nopeg %(nopeg)s): changed in both systems; the '
                      'Presenly value was kept. Review it in Odoo.',
                      name=hr.name or row.name, nopeg=row.nopeg)
                )

            # Kolom milik Presenly yang tidak ikut dikirim balik tidak terlihat
            # oleh pemeriksaan di atas, yang hanya melihat kolom `PUSH_FIELDS`.
            # Tanpa pemeriksaan ini, suntingan Odoo pada kolom seperti `grup` atau
            # `presenly_role` tertimpa tanpa satu pun catatan.
            for kolom_cermin in self.MILIK_PRESENLY:
                if kolom_cermin not in presenly_beda:
                    continue
                dasar = snapshot.get(kolom_cermin)
                sekarang = self._normalkan(
                    kolom_cermin, hr[self.PUSH_TO_HR_FIELD[kolom_cermin]]
                )
                if (dasar or False) != (sekarang or False):
                    summary['conflicts'].append(
                        _('%(name)s (nopeg %(nopeg)s): %(field)s was changed on both '
                          'sides; the Presenly value was kept.',
                          name=hr.name or row.name, nopeg=row.nopeg,
                          field=self.PUSH_TO_HR_FIELD[kolom_cermin])
                    )

            values = self._hr_values(row)
            berubah = {
                key: value for key, value in values.items()
                if self._beda_nilai(hr[key], value)
            }
            if berubah:
                hr.with_context(presenly_skip_push=True).write(berubah)
                summary['updated'] += 1
            else:
                summary['unchanged'] += 1

            self._apply_active(row, hr, summary)
            row.hr_employee_id = hr.id
            self._stamp_synced(row, hr)

        # Keanggotaan kelompok Approver mengikuti hak efektif, sekali per
        # tarikan — bukan per pegawai, supaya tidak ada query berulang.
        self._sync_approver_groups(rows)

        return summary

    @api.model
    def _stamp_synced(self, row, hr):
        """Catat kapan, dari revisi mana, dan dengan nilai apa baris ini disinkronkan.

        Snapshot nilainya yang membuat arah balik bisa membedakan suntingan Odoo
        dari suntingan Presenly tanpa membandingkan jam dua server — dan jam dua
        server tidak bisa dibandingkan dengan andal.
        """
        hr.with_context(presenly_skip_push=True).write({
            'presenly_source_updated_at': row.source_updated_at,
            'presenly_synced_values': self._snapshot_untuk(hr, row),
            'presenly_synced_at': fields.Datetime.now(),
        })

    @staticmethod
    def _normalkan(key, value):
        """Seragamkan satu nilai supaya bisa dibandingkan lintas penyimpanan.

        Tanggal diubah menjadi teks dengan sengaja: snapshot disimpan sebagai
        JSON, dan JSON tidak mengenal tipe tanggal. Menulis objek `date` lalu
        membacanya kembali menghasilkan teks, sehingga tanpa penyeragaman ini
        setiap tarikan akan mengira tanggalnya berubah dan ikut mengirim balik.
        """
        if key == 'birth_date':
            return fields.Date.to_string(value) if value else False
        if key == 'is_active':
            return bool(value)
        if hasattr(value, 'ids'):
            # Relasi: yang dibandingkan id-nya, bukan recordset-nya. Tanpa ini,
            # snapshot selalu terlihat berbeda dan tarikan menulis berulang.
            return value.id or False
        return value or False

    @staticmethod
    def _nilai_banding(nilai):
        """Nilai yang bisa dibandingkan lintas penyimpanan.

        Relasi dibaca sebagai id; angka dan teks dibiarkan apa adanya. Tanpa ini,
        `hr[kolom].id` dipakai untuk kolom yang bukan relasi dan gagal di situ —
        dan itu hanya muncul saat nilainya benar-benar berbeda.
        """
        if hasattr(nilai, 'ids'):
            return nilai.id or False
        return nilai or False

    @staticmethod
    def _beda_nilai(sekarang, baru):
        """Apakah nilainya berbeda — termasuk untuk kolom relasi.

        Membandingkan recordset dengan angka tidak bisa diandalkan: recordset
        kosong lolos begitu saja, yang terisi melempar, dan gejalanya hanya
        muncul saat nilainya benar-benar berubah. Karena itu relasinya
        dibandingkan lewat id — bentuk yang sama dengan yang ditulis ke database.
        """
        return PresenlySaasEmployee._nilai_banding(sekarang) != PresenlySaasEmployee._nilai_banding(baru)

    @api.model
    def _sync_approver_groups(self, rows):
        """Samakan keanggotaan kelompok Approver dengan hak yang efektif.

        Kelompok ini **dikelola sinkronisasi**, bukan diisi tangan: yang berhak
        ditentukan konfigurasi alur di Presenly, dan salinan aturan itu di sini
        akan cepat atau lambat berbeda pendapat dengan aslinya. Karena itu juga
        pencabutannya disengaja — kalau seseorang dikeluarkan dari alur, menunya
        ikut hilang.

        Yang tidak punya akun Odoo dilewati: tanpa akun, tidak ada yang bisa
        diberi kelompok.
        """
        kumpulan = self.env.ref(
            'presenly_saas_hr.group_presenly_saas_approver', raise_if_not_found=False
        )
        if not kumpulan:
            return
        for row in rows:
            pengguna = row.hr_employee_id.user_id
            if not pengguna:
                continue
            punya = kumpulan in pengguna.group_ids
            if row.can_approve_effective and not punya:
                pengguna.sudo().write({'group_ids': [(4, kumpulan.id)]})
            elif not row.can_approve_effective and punya:
                pengguna.sudo().write({'group_ids': [(3, kumpulan.id)]})

    @api.model
    def _snapshot_untuk(self, hr, row):
        """Nilai yang disepakati kedua sisi, termasuk atasan.

        Atasan ikut disimpan walaupun bukan kolom bersama: tanpa itu, setiap
        pemeriksaan akan mengira atasannya baru berubah dan menimpanya terus —
        termasuk menimpa atasan yang sengaja diubah orang di Odoo.
        """
        # Kunci yang bukan milik sinkronisasi pegawai — misalnya yang dicatat
        # penarikan penempatan — dibiarkan utuh. Menimpanya membuat catatan itu
        # hilang, dan pemeriksaan berikutnya kehilangan dasar untuk melaporkan
        # bahwa nilainya sudah diubah orang di Odoo.
        return dict(
            hr.presenly_synced_values or {},
            **self._odoo_values(hr, self.SHARED_FIELDS),
            manager_nopeg=row.manager_nopeg or False,
        )

    @api.model
    def _odoo_values(self, hr, keys):
        """Nilai kolom bersama, dibaca dari sisi Odoo."""
        return {
            key: self._normalkan(key, hr[self.PUSH_TO_HR_FIELD[key]])
            for key in keys
        }

    @api.model
    def _mirror_values_for(self, row, keys):
        """Nilai kolom bersama, dibaca dari cermin."""
        return {key: self._normalkan(key, row[key]) for key in keys}

    @api.model
    def _beda(self, sekarang, snapshot):
        """Kolom yang nilainya berbeda dari snapshot."""
        snapshot = snapshot or {}
        return {
            key: value for key, value in sekarang.items()
            if (value or False) != (snapshot.get(key) or False)
        }

    @api.model
    def _changed_fields(self, hr):
        """Kolom yang berubah **di Odoo** sejak sinkronisasi terakhir.

        Yang dibandingkan adalah nilai Odoo sekarang dengan snapshot terakhir,
        bukan dengan nilai Presenly sekarang. Kalau dibandingkan dengan nilai
        Presenly, suntingan yang belum tersinkron akan terlihat sebagai "tidak
        ada perubahan", lalu hilang tanpa jejak.

        `is_active` sengaja tidak ikut: status aktif dimiliki Presenly, jadi
        perubahan status di Odoo tidak dianggap sebagai suntingan yang perlu
        dikirim balik.
        """
        snapshot = hr.presenly_synced_values or {}
        return self._beda(self._odoo_values(hr, self.PUSH_FIELDS), snapshot)

    @api.model
    def _push_employee(self, client, hr, summary):
        """Kirim satu pegawai ke Presenly. Galat satu pegawai tidak menghentikan
        pegawai lain."""
        # Baris cerminnya diperlukan untuk menuliskan snapshot yang utuh.
        row = self.sudo().search([('hr_employee_id', '=', hr.id)], limit=1)
        berubah = self._changed_fields(hr)
        if not berubah:
            summary['unchanged'] += 1
            return

        try:
            hasil = client.update_employee(hr.presenly_nopeg, berubah)
        except SaasClientError as exc:
            summary['failed'].append(
                _('%(name)s (nopeg %(nopeg)s): %(error)s',
                  name=hr.name, nopeg=hr.presenly_nopeg, error=str(exc))
            )
            return

        data = hasil.get('data') or {}
        hr.with_context(presenly_skip_push=True).write({
            # Snapshot penuh, bukan hanya yang tadi dikirim: tanpa itu, kolom
            # lain yang kebetulan berbeda akan terus terlihat sebagai perubahan.
            'presenly_synced_values': self._snapshot_untuk(hr, row),
            'presenly_source_updated_at': parse_datetime(data.get('updated_at')),
            'presenly_synced_at': fields.Datetime.now(),
        })
        summary['pushed'] += 1
        summary['fields'] = sorted(set(summary['fields']) | set(berubah))

    @api.model
    def _push_to_presenly(self, company, client):
        """Kirim suntingan yang dibuat di Odoo ke Presenly.

        Yang dikirim hanya kolom yang benar-benar berubah di Odoo sejak
        sinkronisasi terakhir. Kolom yang tidak dikirim tidak ditulis server,
        jadi suntingan yang belum tersinkron tidak terhapus oleh tarikan.
        """
        Mirror = self.sudo()
        rows = Mirror.search([('company_id', '=', company.id), ('hr_employee_id', '!=', False)])
        summary = {'pushed': 0, 'unchanged': 0, 'failed': [], 'fields': []}

        for row in rows:
            hr = row.hr_employee_id
            if not hr.presenly_nopeg:
                continue
            self._push_employee(client, hr, summary)

        return summary

    def _apply_active(self, row, hr, summary):
        """Samakan status aktif, dengan satu pengecualian yang disengaja.

        Menonaktifkan pegawai yang punya akun pengguna Odoo berarti mencabut
        akses orang itu tanpa peringatan di Odoo. Itu dilakukan Presenly, bukan
        di sini, jadi keadaannya dilaporkan untuk diperiksa manual.
        """
        if row.is_active == hr.active:
            return
        aktif = hr.with_context(presenly_skip_push=True)
        if not row.is_active and hr.user_id:
            summary['refused'].append(
                _('%(name)s: Presenly marks this employee inactive, but the Odoo '
                  'employee has a user account. Deactivate it in Odoo if that is '
                  'really intended.', name=row.name or row.nopeg)
            )
            return
        aktif.active = row.is_active
