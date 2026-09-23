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
        string='SIK Group',
        readonly=True,
        help='Group as recorded in Presenly. Informational only.',
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
    presenly_role = fields.Char(
        string='Presenly Role', readonly=True,
        help='Role as recorded in Presenly. Deliberately not an Odoo group: it '
             'never grants access here.',
    )
    presenly_shift = fields.Char(
        string='Presenly Shift', readonly=True,
        help='Shift as recorded in Presenly. Informational only.',
    )

    # PII. Dibatasi grup supaya hanya yang berhak membacanya, dan hanya terisi
    # bila tarikan memang meminta `include_pii`.
    presenly_no_npwp = fields.Char(
        string='NPWP', readonly=True, groups='presenly_saas.group_presenly_saas_manager',
    )
    presenly_no_rekening = fields.Char(
        string='Bank Account', readonly=True, groups='presenly_saas.group_presenly_saas_manager',
    )
    presenly_no_bpjs = fields.Char(
        string='BPJS Kesehatan', readonly=True, groups='presenly_saas.group_presenly_saas_manager',
    )
    presenly_no_bpjs_kes = fields.Char(
        string='BPJS Ketenagakerjaan', readonly=True,
        groups='presenly_saas.group_presenly_saas_manager',
    )

    presenly_source_updated_at = fields.Datetime(
        string='Changed in Presenly At',
        readonly=True,
        copy=False,
        help='The `updated_at` Presenly last reported for this employee.',
    )
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
        if self._presenly_fields_touched(values):
            self._presenly_queue_push()
        return result

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
        string='Last Synced from Presenly',
        readonly=True,
        copy=False,
        help='When this record was last written by the Presenly sync.',
    )


_logger = logging.getLogger(__name__)
