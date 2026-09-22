import logging

from odoo import api, fields, models
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
