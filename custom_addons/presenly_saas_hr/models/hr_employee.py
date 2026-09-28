import logging
from functools import partial

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    """Tempelan sinkronisasi Presenly pada model pegawai native Odoo.

    Satu-satunya model native yang disentuh modul ini, dan sengaja hanya
    **ditambah kolom**, tidak ada kolom bawaan yang diubah artinya maupun
    perilakunya.

    Alasannya: daftar pegawai harus satu. Kalau Odoo dan Presenly masing-masing
    punya daftar sendiri, keduanya akan berbeda dan tidak ada yang bisa dipakai
    sebagai acuan. Rinciannya di `PLAN_HR_SYNC.md`.
    """

    _inherit = 'hr.employee'

    presenly_nopeg = fields.Char(
        string='Presenly Nopeg',
        index=True,
        copy=False,
        help='Employee number from Presenly, and the key the sync matches on. '
             'Type one here to link an employee the sync could not match; the '
             'mirror data for that nopeg is applied straight away. A nopeg that '
             'has not been pulled yet is refused rather than saved, because an '
             'unmatchable number would make the next sync create a duplicate.',
    )
    # ------------------------------------------------------------------
    # Kolom yang datang dari Presenly dan tidak punya padanan native di Odoo.
    # Semuanya milik Presenly: diterapkan saat tarikan, tidak pernah dikirim
    # balik, dan perbedaannya ikut dilaporkan.
    #
    # `presenly_role` sengaja hanya kolom biasa, BUKAN `res.groups`. Kalau peran
    # dari aplikasi menjadi hak akses di Odoo, satu perubahan di sana bisa
    # memberi orang izin yang tidak pernah disetujui siapa pun di sini. Peran itu
    # dipakai untuk mencocokkan approver, bukan untuk memberi akses.
    # ------------------------------------------------------------------
    presenly_group = fields.Char(
        string='Presenly Group',
        readonly=True,
        help='Group as recorded in Presenly. The field is called `grup` there; '
             'this label says where it comes from, because the app two-letter '
             'prefix it used before did not explain anything to a reader here.',
    )
    presenly_can_approve = fields.Boolean(
        string='Approval Flag in Presenly', readonly=True,
        help='The approval flag as stored on the employee in Presenly — nothing '
             'more. The application also grants the right to approve through its '
             'approval configuration, so an employee with this flag off can still '
             'be an approver there (a level listed for them in an active flow). '
             'Never use this field to decide who may approve: ask the approval '
             'step instead.',
    )
    presenly_may_approve = fields.Boolean(
        string='May Approve in Presenly', readonly=True,
        help='The right to approve, as Presenly computes it: the stored flag, an '
             'admin role, being listed in an active approval flow, or managing '
             'someone while a direct-manager flow is active. This — not the '
             'stored flag — is what grants the Approver group here.',
    )
    presenly_role = fields.Char(
        string='Presenly Role', readonly=True,
        help='Role as recorded in Presenly. Deliberately not an Odoo group: it '
             'never grants access here.',
    )
    presenly_shift = fields.Char(
        string='Presenly Shift', readonly=True,
        help='Shift as recorded in Presenly. Informational only. The weekly '
             'pattern of shifts and locations is in the schedule list below.',
    )
    presenly_client_id = fields.Integer(
        string='Branch Client ID', readonly=True, index=True,
        help='The branch this employee is placed at, as an id on the Presenly '
             'side. Kept next to the name so the branch stays readable even when '
             'no Odoo company carries that id.',
    )
    presenly_client_name = fields.Char(
        string='Branch', readonly=True,
        help='Which branch this employee works for, from their primary placement. '
             'Kept as a field of its own instead of making the employee belong to '
             'the client company, so the employee list stays in one company and '
             'remains visible without the multi-company selector. Empty until a '
             'placement names one.',
    )
    presenly_client_ids = fields.Many2many(
        'res.company',
        'hr_employee_presenly_client_rel',
        'employee_id',
        'company_id',
        string='Branches',
        readonly=True,
        copy=False,
        help='Every branch company this employee is placed at right now, taken '
             'from their placements in Presenly. This is the current picture, so '
             'a branch leaves this list when its placement ends. Access to the '
             'company, once given, is never taken back by the sync.',
    )
    presenly_other_company_names = fields.Char(
        string='Also an Employee in',
        compute='_compute_presenly_other_company_names',
        help='Other companies where this same person is also an employee. Odoo '
             'keeps one employee per company, while Presenly keeps one person '
             '(one nopeg), so a person can appear here more than once. Shown so '
             'the reader knows the row they are looking at is not the only one.',
    )

    # PII dari Presenly — NPWP, nomor rekening, BPJS — sengaja TIDAK disalin ke
    # sini. Odoo HR tidak membutuhkannya, dan menaruhnya di sini berarti satu lagi
    # tempat yang harus dijaga kerahasiaannya. Datanya tetap ada di aplikasi.

    presenly_source_updated_at = fields.Datetime(
        string='Changed in Presenly At',
        readonly=True,
        copy=False,
        help='When Presenly last changed this employee: the `updated_at` it '
             'reports. It is Presenly\'s clock, not this server\'s, and it does '
             'not move when a pull here finds nothing new.',
    )

    # ------------------------------------------------------------------
    # Dibaca saja: perusahaan lain tempat orang yang sama juga pegawai
    # ------------------------------------------------------------------
    # Odoo menyimpan satu pegawai per perusahaan, sedangkan Presenly menyimpan
    # satu orang (satu nopeg). Orang yang sama karena itu bisa punya beberapa
    # baris pegawai di sini, dan tanpa penanda ini baris yang sedang dibaca
    # terlihat seperti satu-satunya.
    @api.depends('user_id', 'presenly_nopeg', 'company_id')
    def _compute_presenly_other_company_names(self):
        for employee in self:
            domain = []
            if employee.presenly_nopeg:
                domain.append(('presenly_nopeg', '=', employee.presenly_nopeg))
            if employee.user_id:
                domain.append(('user_id', '=', employee.user_id.id))
            if not domain:
                employee.presenly_other_company_names = False
                continue
            if len(domain) > 1:
                domain = ['|'] + domain
            lain = self.sudo().search(domain + [
                ('id', '!=', employee.id),
                ('company_id', '!=', employee.company_id.id),
            ])
            employee.presenly_other_company_names = ', '.join(
                sorted(set(lain.mapped('company_id.name')))
            ) or False

    # ------------------------------------------------------------------
    # Kirim balik saat disimpan
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, values_list):
        employees = super().create(values_list)
        # Nopeg saat pembuatan **tidak** diperiksa di sini, dan itu disengaja:
        # pegawai Odoo boleh dibuat lebih dulu — bahkan sebelum tarikan pertama —
        # lalu dicocokkan oleh tarikan lewat nopeg-nya. Memaksa cerminnya sudah ada
        # akan memblokir alur yang sah itu.
        #
        # Pemeriksaannya ada di `write`, saat nopeg sebuah pegawai yang sudah ada
        # **diubah**: di situlah kunci penghubungnya berpindah, dan di situ pula
        # nomor yang salah atau sudah dipakai orang lain berbahaya.
        employees._presenly_queue_push()
        return employees

    def write(self, values):
        result = super().write(values)
        if 'presenly_nopeg' in values:
            self._presenly_link_from_nopeg()
        if 'user_id' in values:
            # Pengguna baru ditautkan: cabang yang sudah tercatat langsung
            # diberikan, bukan menunggu tarikan berikutnya. Tanpa ini, pertanyaan
            # "akunnya sudah saya buat, kenapa ia belum bisa masuk cabangnya"
            # hanya terjawab besok.
            self._presenly_grant_branch_access()
        if self._presenly_fields_touched(values):
            self._presenly_queue_push()
        return result

    def _presenly_grant_branch_access(self):
        """Tambahkan perusahaan cabang ke daftar perusahaan pengguna pegawai ini.

        Hanya **menambah**, tidak pernah mencabut: akses yang sudah diberikan
        dibiarkan, supaya tidak ada kejutan berupa hilangnya perusahaan di tengah
        pekerjaan. Yang diberikan hanya perusahaan hasil cermin klien.

        Dipanggil dari dua tempat, dan keduanya memang perlu: penarikan
        penempatan (cabang baru muncul) dan penautan pengguna (akun baru muncul
        untuk cabang yang sudah ada). Mengembalikan jumlah yang ditambahkan.
        """
        ditambahkan = 0
        for employee in self:
            if not employee.user_id or not employee.presenly_client_ids:
                continue
            kurang = employee.presenly_client_ids - employee.user_id.company_ids
            if not kurang:
                continue
            employee.user_id.sudo().write({'company_ids': [(4, c.id) for c in kurang]})
            keterangan = _('%(user)s can now work in %(companies)s, from their '
                           'placements in Presenly.',
                           user=employee.user_id.display_name,
                           companies=', '.join(kurang.mapped('name')))
            self.env['presenly.saas.sync.log'].sudo()._record(
                employee.company_id, 'access.companies', success=True,
                error_message=keterangan,
            )
            _logger.info(
                'Presenly SaaS: akses perusahaan ditambahkan untuk %s: %s',
                employee.user_id.display_name, ', '.join(kurang.mapped('name')),
            )
            ditambahkan += len(kurang)
        return ditambahkan

    def _presenly_link_from_nopeg(self):
        """Tautkan pegawai ini ke cermin Presenly lewat nopeg yang diketik pengguna.

        Nopeg yang belum pernah ditarik **ditolak**, bukan disimpan. Nopeg adalah
        kunci pencocokan: menyimpan nomor yang tidak punya pasangan di cermin
        membuat pegawai ini tidak bisa dicocokkan, dan tarikan berikutnya akan
        membuat duplikatnya.

        Penulisan dari sinkronisasi sendiri dilewati — penanda `presenly_skip_push`
        dipakai untuk itu, sama seperti di tempat lain yang menandai "ini bukan
        suntingan pengguna".
        """
        if self.env.context.get('presenly_skip_push'):
            return
        Mirror = self.env['presenly.saas.employee'].sudo()
        for employee in self:
            nopeg = (employee.presenly_nopeg or '').strip()
            if not nopeg:
                continue
            cermin = Mirror.search([
                ('nopeg', '=', nopeg), ('company_id', '=', employee.company_id.id),
            ], limit=1) or Mirror.search([('nopeg', '=', nopeg)], limit=1)
            if not cermin:
                raise UserError(_(
                    'No Presenly employee with nopeg %(nopeg)s has been pulled yet. '
                    'Run "Pull Employees" first, then set the nopeg again.'
                ) % {'nopeg': nopeg})
            # Nopeg yang sudah dipegang pegawai lain tidak boleh dipakai di sini.
            # Dua pegawai dengan nopeg sama membuat sinkronisasi menolak menyentuh
            # keduanya, jadi menyimpannya justru mengunci data yang mau ditautkan.
            lain = self.env['hr.employee'].sudo().with_context(active_test=False).search([
                ('presenly_nopeg', '=', nopeg),
                ('id', 'not in', employee.ids),
            ], limit=1)
            if lain:
                raise UserError(_(
                    'Nopeg %(nopeg)s is already used by %(other)s. Clear it there '
                    'first, or link that employee instead.'
                ) % {'nopeg': nopeg, 'other': lain.display_name})
            # Sinkronisasi per perusahaan menautkan barisnya sendiri lewat nopeg,
            # lalu menerapkan nilainya. Tidak ada jalan pintas di sini: jalur yang
            # dipakai adalah jalur yang sama dengan tarikan biasa, supaya aturannya
            # cuma satu.
            cermin.with_context(presenly_skip_push=True)._sync_to_hr(cermin.company_id)

    def _presenly_fields_touched(self, values):
        """Apakah penulisan ini menyentuh kolom yang ikut disinkronkan?"""
        Mirror = self.env['presenly.saas.employee']
        hr_fields = {Mirror.PUSH_TO_HR_FIELD[key] for key in Mirror.PUSH_FIELDS}
        return bool(hr_fields & set(values or {}))

    def _presenly_queue_push(self):
        """Antrekan pengiriman ke Presenly untuk dijalankan SETELAH commit.

        Dua alasan, keduanya penting:

        1. Kalau transaksinya batal, tidak ada yang terkirim. Mengirim di
           tengah transaksi bisa mengabarkan perubahan yang akhirnya tidak jadi.
        2. Panggilan jaringan tidak boleh memperlambat atau menggagalkan
           penyimpanan yang dilakukan pengguna. Kegagalan kirim tidak boleh
           membuat simpanan Odoo ikut batal.
        """
        # Sinkronisasi itu sendiri menulis ke model ini; tanpa penanda ini
        # setiap tarikan akan memicu pengiriman balik dan berputar tanpa henti.
        if self.env.context.get('presenly_skip_push'):
            return
        linked = self.filtered('presenly_nopeg')
        if not linked:
            return
        self.env.cr.postcommit.add(partial(linked._presenly_push_after_commit, linked.ids))

    @api.model
    def _presenly_push_after_commit(self, ids):
        """Kirim satu pegawai ke Presenly. Tidak pernah melempar.

        Dipanggil setelah commit, jadi transaksi tidak bisa dibatalkan lagi:
        galat di sini hanya bisa dilaporkan, bukan diperbaiki dengan rollback.
        """
        Config = self.env['presenly.saas.config'].sudo()
        Mirror = self.env['presenly.saas.employee'].sudo()
        for employee in self.sudo().browse(ids).exists():
            if not employee.presenly_nopeg:
                continue
            # Konfigurasi dicari lewat induk: pegawai ini boleh jadi milik
            # perusahaan hasil cermin klien, sedangkan integrasinya dimiliki
            # perusahaan pemasang.
            config = Config._config_for_record(employee)
            if not config:
                continue
            try:
                client = config._client()
                summary = {'pushed': 0, 'unchanged': 0, 'failed': [], 'fields': []}
                Mirror._push_employee(client, employee, summary)
            except Exception as exc:  # noqa: BLE001 - tidak boleh sampai ke pengguna
                _logger.warning(
                    "Presenly SaaS: immediate push failed for employee %s: %s",
                    employee.id,
                    exc,
                )
                continue
            if summary['failed']:
                _logger.warning(
                    "Presenly SaaS: could not send employee %s to Presenly: %s",
                    employee.id,
                    summary['failed'][0],
                )

    presenly_saas_config_id = fields.Many2one(
        'presenly.saas.config',
        string='Presenly Connection',
        readonly=True,
        copy=False,
        ondelete='set null',
        help='The configuration that owns this employee. Recorded on first '
             'successful contact, so later write-backs go to the same Presenly '
             'tenant even when several connections are active.',
    )
    presenly_synced_values = fields.Json(
        string='Last Synced Values',
        readonly=True,
        copy=False,
        help='The mapped fields as they were at the last successful sync. Used to '
             'tell an edit made in Odoo apart from an edit made in Presenly, '
             'without relying on comparing clocks across two servers.',
    )
    presenly_synced_at = fields.Datetime(
        string='Last Written by Sync',
        readonly=True,
        copy=False,
        help='When this record was last written by the Presenly sync — this '
             'server\'s clock, not Presenly\'s. A pull that finds nothing to '
             'change does not update it, so read it as "last applied", not '
             '"last checked".',
    )


_logger = logging.getLogger(__name__)
