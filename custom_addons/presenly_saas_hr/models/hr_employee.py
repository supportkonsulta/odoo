import logging
from functools import partial

from odoo import _, api, fields, models


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
        help='Employee number from Presenly. This is the key the sync matches on, '
             'so it is only ever written by the sync. Changing it by hand makes '
             'the record unmatchable, and the next sync would create a duplicate.',
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
        employees._presenly_queue_push()
        return employees

    def write(self, values):
        result = super().write(values)
        if self._presenly_fields_touched(values):
            self._presenly_queue_push()
        return result

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
            config = Config.search([
                ('company_id', '=', employee.company_id.id),
                ('enabled', '=', True),
                ('active', '=', True),
            ], limit=1)
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
