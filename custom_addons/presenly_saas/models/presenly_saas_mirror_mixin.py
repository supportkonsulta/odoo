import logging

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PresenlySaasMirrorMixin(models.AbstractModel):
    """Dasar untuk cermin resource referensi dari Presenly SaaS.

    Resource referensi (lokasi kerja, shift, mode absen, hari libur, setup hari
    kerja) tidak punya periode: isinya adalah keadaan terkini. Karena itu
    penarikannya **mengganti seluruh isi** untuk company tersebut, bukan
    menumpuk. Tabelnya kecil, jadi ini sederhana dan selalu konsisten dengan
    server.

    Hal yang sama tidak berlaku untuk data berperiode (log presensi, rekap),
    yang mengganti per rentang tanggal saja.

    Setiap model yang memakai mixin ini mengisi:

    - `_mirror_resource`: nama resource di API, mis. `work-locations`
    - `_mirror_values(company, row)`: petakan satu baris API ke kolom model
    """

    _name = 'presenly.saas.mirror.mixin'
    _description = 'Presenly SaaS Mirror Mixin'

    _mirror_resource = None

    # Diisi oleh cermin berperiode (pengajuan). Kalau kosong, model dianggap
    # resource referensi dan penarikannya mengganti seluruh isi.
    _mirror_date_field = None

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    # `external_id` menyimpan id baris di sisi Presenly dan hanya dipakai
    # sinkronisasi untuk mencocokkan. Sengaja tanpa label yang enak dibaca dan
    # tanpa tampilan: bagi pengguna itu angka yang tidak bisa dipakai untuk apa pun.
    external_id = fields.Integer(
        string='Presenly Row ID',
        required=True,
        index=True,
        # `aggregator=False` membuat Odoo TIDAK menawarkannya sebagai ukuran
        # pivot. Tanpa ini, seluruh kolom id mentah muncul di daftar "Measures"
        # pada view pivot: angka yang tidak bisa dipakai untuk apa pun, tapi ikut
        # terdaftar di antarmuka pengguna.
        aggregator=False,
        help='Row id on the Presenly side. Used by the sync to match records. Not '
             'shown in any view: for a user it is a number that cannot be used for '
             'anything.',
    )
    fetched_at = fields.Datetime(string='Last Pulled', readonly=True, index=True)
    source_created_at = fields.Datetime(string='Created on SaaS')
    source_updated_at = fields.Datetime(string='Updated on SaaS')

    # Field bersarang dari API disimpan apa adanya, supaya tidak ada informasi
    # yang hilang hanya karena belum dibuatkan kolomnya.
    raw_payload = fields.Json(string='Raw Payload')

    _mirror_company_external_uniq = models.Constraint(
        'unique(company_id, external_id)',
        'A row may only be mirrored once per company.',
    )

    @api.model
    def _mirror_values(self, company, row):
        raise NotImplementedError(
            'Model %s harus mengisi _mirror_values().' % self._name
        )

    @api.model
    def _mirror_replace(self, company, rows):
        """Ganti seluruh isi cermin untuk company ini.

        Seluruh baris dipetakan lebih dulu, baru tabel lama dihapus. Dengan
        begitu kegagalan di tengah pemetaan tidak meninggalkan cermin kosong.
        """
        return self._mirror_write(company, rows, domain=[('company_id', '=', company.id)])

    @api.model
    def _mirror_replace_range(self, company, rows, date_from, date_to):
        """Ganti cermin hanya untuk rentang tanggal tertentu.

        Dipakai data berperiode seperti pengajuan cuti atau lembur: menarik
        September tidak boleh menghapus isi Agustus. Baris di luar rentang
        dibiarkan apa adanya.
        """
        if not self._mirror_date_field:
            raise UserError(
                'Model %s belum mengisi _mirror_date_field, jadi tidak bisa '
                'mengganti per rentang.' % self._name
            )
        domain = [
            ('company_id', '=', company.id),
            (self._mirror_date_field, '>=', date_from),
            (self._mirror_date_field, '<=', date_to),
        ]
        return self._mirror_write(company, rows, domain=domain)

    @api.model
    def _mirror_upsert(self, company, rows):
        """Tambahkan atau perbarui baris, **tanpa menghapus apa pun**.

        Dipakai penarikan tambahan, yang hanya mengambil baris yang berubah sejak
        penanda waktu terakhir. Karena itu ia tidak boleh menghapus seperti
        penggantian per rentang: baris yang tidak ikut terambil bukan baris basi,
        melainkan baris yang memang tidak berubah.

        Pencocokannya memakai `external_id`, penanda yang sama yang dipakai
        sinkronisasi untuk mengenali baris — dan yang dijaga constraint
        `(company_id, external_id)`.
        """
        Mirror = self.sudo()
        values_list = []
        for row in rows:
            values = self._mirror_values(company, row)
            if values:
                values_list.append(values)
        if not values_list:
            return 0

        existing = {
            baris.external_id: baris
            for baris in Mirror.search([
                ('company_id', '=', company.id),
                ('external_id', 'in', [values['external_id'] for values in values_list]),
            ])
        }

        ditulis = 0
        for values in values_list:
            baris = existing.get(values['external_id'])
            if baris:
                baris.write(values)
            else:
                Mirror.create(values)
            ditulis += 1
        return ditulis

    @api.model
    def _mirror_write(self, company, rows, domain):
        """Petakan semua baris, hapus yang lama pada `domain`, lalu buat baru."""
        Mirror = self.sudo()
        values_list = []
        for row in rows:
            values = self._mirror_values(company, row)
            if values:
                values_list.append(values)

        stale = Mirror.search(domain)
        if stale:
            stale.unlink()

        if values_list:
            Mirror.create(values_list)
        return len(values_list)

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None,
                        count_limit=None):
        """Segarkan cermin sebelum daftarnya dibaca.

        Dipasang di mixin yang diwarisi hampir seluruh cermin. Yang memicu hanya
        pembacaan daftar: pivot, grafik, dan laporan tidak menyentuh jaringan.

        Model yang tidak mewarisi mixin ini — log presensi dan rekap, yang punya
        radas penulisan sendiri — memasang penimpaan yang sama dan memanggil
        `_refresh_from_page()` yang sama.
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
    @api.depends(
        'approval_has_workflow',
        'approval_current_level',
        'approval_step_ids.level',
        'approval_step_ids.approver_label',
    )
    def _compute_approval_waiting_for(self):
        for request in self:
            if not request.approval_has_workflow or not request.approval_current_level:
                request.approval_waiting_for = False
                continue
            langkah = request.approval_step_ids.filtered(
                lambda step: step.level == request.approval_current_level
            )
            request.approval_waiting_for = langkah[:1].approver_label or False
