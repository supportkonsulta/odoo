import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PresenlySaasSyncMark(models.Model):
    """Penanda waktu penarikan tambahan, satu baris per (perusahaan, jenis).

    Penarikan tambahan mengirim `updated_since = penanda terakhir`, jadi yang
    terambil hanya baris yang berubah sejak penarikan sebelumnya. Penandanya
    **dipisah per jenis**, bukan satu untuk semuanya: kegagalan di modul ini
    dikembalikan sebagai nilai dan bukan dilempar, sehingga jenis yang gagal
    tidak boleh ikut menaikkan penanda jenis lain. Kalau ikut, perubahan pada
    jenis itu tidak akan pernah terambil lagi.

    Nilainya diambil dari waktu server Presenly (`meta.server_time`), bukan jam
    Odoo. Yang dibandingkan adalah `updated_at` milik server, dan dua jam yang
    berbeda tidak boleh diadu.
    """

    _name = 'presenly.saas.sync.mark'
    _description = 'Presenly SaaS Incremental Sync Mark'
    _order = 'dataset'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        ondelete='cascade',
        index=True,
    )
    # Nama resource di API: leaves, overtimes, medical-certificates, dst.
    dataset = fields.Char(string='Dataset', required=True, index=True)
    last_synced_at = fields.Datetime(
        string='Changes Seen Until',
        required=True,
        help='Server time up to which changes have been picked up. The next '
             'incremental pull asks for everything changed after this.',
    )

    _company_dataset_uniq = models.Constraint(
        'unique(company_id, dataset)',
        'A dataset may only have one sync mark per company.',
    )

    @api.model
    def _since(self, company, dataset, overlap_minutes):
        """Batas bawah `updated_since`, atau ``None`` kalau belum pernah ditarik.

        Tumpang tindih beberapa menit dipakai dengan sengaja: API menyaring
        dengan `updated_at > since`, sehingga baris yang berubah pada detik yang
        sama dengan penanda terakhir bisa terlewat. Mengulang beberapa menit
        terakhir jauh lebih murah daripada kehilangan satu pengajuan.
        """
        mark = self.sudo().search([
            ('company_id', '=', company.id),
            ('dataset', '=', dataset),
        ], limit=1)
        if not mark:
            return None
        return mark.last_synced_at - timedelta(minutes=overlap_minutes)

    @api.model
    def _advance(self, company, dataset, server_time):
        """Catat sampai kapan jenis ini sudah terambil."""
        mark = self.sudo().search([
            ('company_id', '=', company.id),
            ('dataset', '=', dataset),
        ], limit=1)
        if mark:
            mark.last_synced_at = server_time
        else:
            self.sudo().create({
                'company_id': company.id,
                'dataset': dataset,
                'last_synced_at': server_time,
            })
