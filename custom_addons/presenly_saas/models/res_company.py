"""Perusahaan Odoo yang berasal dari klien Presenly.

Di Presenly, satu tenant bisa punya beberapa **klien** (dipakai sebagai
"internal company" di seluruh data). Di Odoo, padanannya adalah `res.company`:
itulah yang memisahkan data antar entitas, dan `check_company` pada model HR
menuntut perusahaannya benar-benar ada.

Perusahaan yang dibuat di sini **tidak pernah dihapus otomatis**. Menghapus
`res.company` ikut membawa data akuntansi dan konfigurasi yang menggantung padanya,
dan itu bukan akibat yang pantas ditimbulkan oleh data yang hilang dari respons
API. Klien yang hilang dilaporkan, bukan dihapus.
"""

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # `aggregator=False`: id dari sisi Presenly tidak bisa dipakai untuk apa pun
    # oleh pengguna, jadi tidak perlu ditawarkan sebagai ukuran pivot.
    presenly_client_id = fields.Integer(
        string='Presenly Client ID',
        index=True,
        copy=False,
        aggregator=False,
        help='Client id on the Presenly side. Used by the sync to match the '
             'company; not something a user can look up there.',
    )
    presenly_business_sector = fields.Char(
        string='Business Sector',
        help='Sector as recorded by the client in Presenly. Kept here because '
             'Odoo has no equivalent field with the same meaning.',
    )
    presenly_synced_at = fields.Datetime(string='Synced from Presenly At', readonly=True)

    _presenly_client_uniq = models.Constraint(
        'unique(presenly_client_id)',
        'One Odoo company may only mirror one Presenly client.',
    )
