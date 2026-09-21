import logging

from odoo import api, fields, models

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

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    external_id = fields.Integer(
        string='ID di Presenly', required=True, index=True,
    )
    fetched_at = fields.Datetime(readonly=True, index=True)
    source_created_at = fields.Datetime(string='Dibuat di SaaS')
    source_updated_at = fields.Datetime(string='Diubah di SaaS')

    # Field bersarang dari API disimpan apa adanya, supaya tidak ada informasi
    # yang hilang hanya karena belum dibuatkan kolomnya.
    raw_payload = fields.Json(string='Payload Mentah')

    _mirror_company_external_uniq = models.Constraint(
        'unique(company_id, external_id)',
        'Satu baris hanya boleh tercermin sekali per company.',
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
        Mirror = self.sudo()
        values_list = []
        for row in rows:
            values = self._mirror_values(company, row)
            if values:
                values_list.append(values)

        stale = Mirror.search([('company_id', '=', company.id)])
        if stale:
            stale.unlink()

        if values_list:
            Mirror.create(values_list)
        return len(values_list)
