"""Menemukan siapa yang perlu akun Odoo supaya bisa menyetujui.

Akun Odoo dibuat manual, dan itu memang seharusnya: di dalamnya ada hak akses dan
kata sandi, bukan sekadar data pegawai. Tetapi mengerjakannya dari ingatan mudah
salah — orangnya bisa belasan, dan yang perlu akun hanya sebagian.

Halaman ini menyaringnya dari data yang sudah ada. Dua kelompok yang perlu akun:

1. **Yang keputusannya sedang ditunggu.** Nopeg yang muncul di langkah pengajuan
   yang belum diputuskan. Ini kelompok yang paling mendesak: ada pengajuan
   menunggu, dan tanpa akun tidak ada tombolnya.
2. **Yang punya bawahan.** Level terakhir di kelima alur tenant ini bertipe
   `direct_manager`, jadi siapa pun yang punya bawahan akan menerima pengajuan
   cepat atau lambat.

Daftar ini juga berfungsi sebagai pemeriksa: kalau ada pengajuan menunggu tetapi
tombolnya tidak muncul, jawabannya ada di sini — bukan di kode.
"""

import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)

# Kelima model langkah, dengan kolom yang sama dari mixin. Dipakai untuk mencari
# nopeg yang sedang ditunggu keputusannya.
STEP_MODELS = [
    'presenly.saas.approval.step.leave',
    'presenly.saas.approval.step.overtime',
    'presenly.saas.approval.step.medical.certificate',
    'presenly.saas.approval.step.attendance.correction',
    'presenly.saas.approval.step.shift.swap',
]


class HrEmployee(models.Model):
    """Penyaring approver yang belum punya akun Odoo."""

    _inherit = 'hr.employee'

    @api.model
    def _presenly_nopegs_menunggu_keputusan(self):
        """Nopeg yang sedang ditunggu keputusannya, menurut langkah pengajuan."""
        nopegs = set()
        for nama_model in STEP_MODELS:
            langkah = self.env[nama_model].sudo().search([
                ('acted_at', '=', False),
                ('expected_nopeg', '!=', False),
            ])
            nopegs.update(langkah.mapped('expected_nopeg'))
        return nopegs

    @api.model
    def _presenly_nopegs_punya_bawahan(self):
        """Nopeg dari setiap atasan, karena level `direct_manager` menuju ke sana."""
        bawahan = self.sudo().with_context(active_test=False).search([
            ('parent_id', '!=', False),
        ])
        return {nopeg for nopeg in bawahan.mapped('parent_id.presenly_nopeg') if nopeg}

    @api.model
    def _presenly_perlu_akun(self):
        """Pegawai Presenly yang perlu akun Odoo tetapi belum punya."""
        nopegs = self._presenly_nopegs_menunggu_keputusan() | self._presenly_nopegs_punya_bawahan()
        if not nopegs:
            return self.sudo().browse()
        return self.sudo().with_context(active_test=False).search([
            ('presenly_nopeg', 'in', list(nopegs)),
            ('user_id', '=', False),
        ])

    @api.model
    def action_presenly_approvers_without_account(self):
        """Buka daftar approver yang belum punya akun Odoo.

        Memakai action dengan ids yang sudah dihitung, bukan filter domain: yang
        dicari adalah irisan tiga model berbeda, dan domain tidak bisa
        menyatakannya tanpa menyimpan hasilnya terlebih dahulu.
        """
        pegawai = self._presenly_perlu_akun()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Approvers Without an Odoo Account'),
            'res_model': 'hr.employee',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pegawai.ids)],
            'help': _(
                '<p>These employees are expected to decide a request, or have someone '
                'reporting to them, but they have no Odoo account yet. Create the '
                'account from the employee form — Odoo links it to the employee by '
                'itself, and the nopeg is already filled in.</p>'
            ),
        }
