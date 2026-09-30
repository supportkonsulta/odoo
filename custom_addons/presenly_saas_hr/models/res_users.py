from odoo import api, fields, models


class ResUsers(models.Model):
    """Nopeg Presenly milik pengguna, dipakai aturan akses "milik sendiri".

    Kolom ini ada karena `res.users.employee_id` tidak bisa dipakai untuk itu.
    Nilainya adalah pegawai pada **perusahaan yang sedang aktif**
    (`addons/hr/models/res_users.py`), sedangkan record pegawai di sini berada di
    perusahaan integrasi. Pegawai yang sedang bekerja di perusahaan cabang karena
    itu akan kehilangan pandangannya sendiri.

    Karena kolom ini dipakai di `domain_force` aturan akses, ia harus tersimpan
    dan bisa dicari: field terhitung yang tidak disimpan tidak bisa dipakai
    menyaring tanpa metode `search` sendiri.
    """

    _inherit = 'res.users'

    presenly_nopeg = fields.Char(
        string='Presenly Nopeg',
        compute='_compute_presenly_nopeg',
        store=True,
        help='Presenly employee number of this user, taken from the linked '
             'employee. Filled no matter which company is active, because the '
             'employee record lives in the integration company.',
    )

    @api.depends('employee_ids.presenly_nopeg')
    def _compute_presenly_nopeg(self):
        # Dibaca lewat pencarian langsung, bukan `user.employee_ids`: relasi itu
        # disaring perusahaan yang sedang aktif (`_employee_ids_domain` di
        # `hr`), dan saringan itulah yang membuat nilainya bisa kosong padahal
        # pegawainya ada.
        Pegawai = self.env['hr.employee'].sudo()
        for user in self:
            pegawai = Pegawai.search([
                ('user_id', '=', user.id),
                ('presenly_nopeg', '!=', False),
            ], limit=1)
            user.presenly_nopeg = pegawai.presenly_nopeg or False
