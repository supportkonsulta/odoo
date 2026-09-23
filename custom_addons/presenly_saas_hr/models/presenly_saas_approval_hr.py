"""Memutuskan pengajuan dari Odoo.

Modul inti sudah menampilkan rantai persetujuan: siapa yang seharusnya memutuskan
tiap level, siapa yang sudah memutuskan, dan di level mana pengajuan itu berhenti.
Bagian ini menambahkan kemampuannya **memutuskan**.

Tiga hal yang menentukan bentuknya:

1. **Odoo tidak menghitung jenjang.** Yang boleh memutuskan ditentukan server;
   tombol di sini hanya ditampilkan kepada orang yang menurut langkah persetujuan
   memang berhak. Kalau tombolnya muncul karena salah hitung, server tetap
   menolaknya — dan penolakan itu ditampilkan, bukan didiamkan.
2. **Yang berhak dicocokkan lewat nopeg.** Untuk level bertipe `user`, server
   mengirim siapa orangnya. Untuk level bertipe `direct_manager`, yang berhak
   adalah atasan pemohon — dan atasan itu sudah disalin dari Presenly ke
   `hr.employee.parent_id`, jadi tidak perlu aturan baru.
3. **Level bertipe `role` dan `permission` tidak diputuskan dari sini.** Yang
   berhak pada level seperti itu adalah sekumpulan orang, bukan satu orang yang
   bisa dicocokkan ke satu pengguna. Tombolnya tidak muncul, dan itu keadaan yang
   disengaja, bukan kekurangan yang tersembunyi.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.presenly_saas.services.saas_client import SaasClientError

_logger = logging.getLogger(__name__)

# Model pengajuan yang bisa diputuskan dari Odoo, beserta nama resource-nya di API.
# Hanya yang sudah diverifikasi namanya; sisanya dibiarkan tanpa tombol sampai
# benar-benar dipakai, daripada menebak nama resource dan gagal saat diklik.
# Hanya yang backend-nya juga sudah melayani keputusan. Lembur sengaja belum di
# sini: kalau tombolnya muncul padahal endpoint-nya belum ada, yang terjadi adalah
# penolakan yang membingungkan — lebih baik tombolnya belum ada.
RESOURCE_BY_MODEL = {
    'presenly.saas.leave': 'leaves',
}


class PresenlySaasSubmissionMixin(models.AbstractModel):
    """Tambahan pada semua pengajuan: siapa yang berhak, dan tombolnya."""

    _inherit = 'presenly.saas.submission.mixin'

    presenly_odoo_approver_id = fields.Many2one(
        'res.users',
        string='Approver Now',
        compute='_compute_presenly_approver',
        help='The Odoo user who may decide the level that is running now, matched '
             'from the approval step. Empty when the step expects a group of people '
             '(a role or a permission) rather than one person, or when that person '
             'has no Odoo user.',
    )
    presenly_can_decide = fields.Boolean(
        string='You May Decide',
        compute='_compute_presenly_approver',
        help='True only for the user who may decide the running level.',
    )
    presenly_decidable = fields.Boolean(
        string='Decidable From Odoo',
        compute='_compute_presenly_approver',
        help='Whether this request type can be decided from Odoo at all.',
    )

    # `employee_nopeg` sengaja TIDAK ada di daftar ini: hanya sebagian model
    # pengajuan yang punya kolom itu, dan Odoo menolak dependensi yang tidak ada
    # di semua model yang memakai mixin. Atasan pemohon pun tinggal di model lain
    # (`hr.employee.parent_id`), yang memang tidak bisa dilacak sebagai dependensi.
    # Yang dilacak adalah langkah dan levelnya — dan keduanya berubah tepat saat
    # keputusan berpindah, yaitu saat nilai ini perlu dihitung ulang.
    @api.depends(
        'approval_step_ids.level', 'approval_step_ids.expected_nopeg',
        'approval_step_ids.acted_at', 'approval_step_ids.approver_type',
        'approval_current_level',
    )
    # Nilainya bergantung pada siapa yang melihat, dan itu harus dinyatakan.
    # Tanpanya, nilai yang terhitung untuk satu pengguna dipakai ulang untuk
    # pengguna lain dalam transaksi yang sama — dan tombolnya muncul di tempat
    # yang salah.
    @api.depends_context('uid')
    def _compute_presenly_approver(self):
        for pengajuan in self:
            pengguna = pengajuan._presenly_approver_user()
            pengajuan.presenly_odoo_approver_id = pengguna
            pengajuan.presenly_can_decide = bool(pengguna) and pengguna == self.env.user
            pengajuan.presenly_decidable = pengajuan._presenly_resource() in RESOURCE_BY_MODEL.values()

    # ------------------------------------------------------------------
    # Pencocokan approver
    # ------------------------------------------------------------------
    def _presenly_resource(self):
        """Nama resource pengajuan ini di API, kalau dikenal."""
        self.ensure_one()
        return RESOURCE_BY_MODEL.get(self._name, '')

    def _presenly_approver_user(self):
        """Pengguna Odoo yang berhak memutuskan level yang sedang berjalan.

        Kosong berarti tidak ada satu orang pun yang bisa ditunjuk: levelnya milik
        sekumpulan orang, langkahnya sudah diputuskan, atau orangnya tidak punya
        akun Odoo. Ketiganya dibiarkan kosong, bukan ditebak.
        """
        self.ensure_one()
        if not self.approval_current_level:
            return self.env['res.users'].browse()

        # Langkah yang belum diputuskan di level berjalan. Dipilih lewat
        # `acted_at`, bukan lewat nama status, supaya tidak bergantung pada
        # kosakata status yang bisa berubah.
        langkah = self.approval_step_ids.filtered(
            lambda baris: baris.level == self.approval_current_level and not baris.acted_at
        )[:1]
        if not langkah:
            return self.env['res.users'].browse()

        if langkah.approver_type == 'user':
            return self._presenly_user_by_nopeg(langkah.expected_nopeg)
        if langkah.approver_type == 'direct_manager':
            return self._presenly_manager_user()
        # `role` dan `permission`: yang berhak sekumpulan orang, bukan satu orang.
        return self.env['res.users'].browse()

    @api.model
    def _presenly_user_by_nopeg(self, nopeg):
        """Pengguna Odoo yang memegang nopeg ini, kalau ada."""
        if not nopeg:
            return self.env['res.users'].browse()
        pegawai = self.env['hr.employee'].sudo().with_context(active_test=False).search(
            [('presenly_nopeg', '=', nopeg)], limit=1
        )
        return pegawai.user_id

    def _presenly_manager_user(self):
        """Atasan pemohon, menurut data yang disalin dari Presenly."""
        self.ensure_one()
        nopeg = self.employee_nopeg if 'employee_nopeg' in self._fields else False
        if not nopeg:
            return self.env['res.users'].browse()
        pemohon = self.env['hr.employee'].sudo().with_context(active_test=False).search(
            [('presenly_nopeg', '=', nopeg)], limit=1
        )
        return pemohon.parent_id.user_id

    # ------------------------------------------------------------------
    # Tombol
    # ------------------------------------------------------------------
    def action_presenly_approve(self):
        return self._presenly_decide('approve')

    def action_presenly_reject(self):
        return self._presenly_decide('reject')

    def _presenly_decide(self, decision):
        """Kirim keputusan ke Presenly, lalu segarkan keadaan barunya.

        Semua penolakan server diterjemahkan menjadi pesan yang terlihat. Tidak
        ada jalur yang berakhir tanpa kabar: pengguna yang menekan tombol harus
        tahu keputusannya diterima atau ditolak, dan kenapa.
        """
        self.ensure_one()
        resource = self._presenly_resource()
        if not resource:
            raise UserError(_(
                'This request type cannot be decided from Odoo yet.'
            ))

        Config = self.env['presenly.saas.config'].sudo()
        config = Config._config_for_company(self.env.company)
        if not config or not config.allow_approval_from_odoo:
            raise UserError(_(
                'Deciding requests from Odoo is not enabled. Turn on '
                '"Decide Requests from Odoo" on the Presenly connection first.'
            ))

        nopeg = self.env.user.employee_id.presenly_nopeg
        if not nopeg:
            raise UserError(_(
                'Your Odoo user is not linked to a Presenly nopeg. Ask for the nopeg '
                'to be filled in on your employee record first — Presenly identifies '
                'who decided by the nopeg.'
            ))

        if self._presenly_approver_user() != self.env.user:
            raise UserError(_(
                'You are not the approver for the level that is running now. '
                'Approver now: %(name)s.', name=self.presenly_odoo_approver_id.name or _('nobody in Odoo'),
            ))

        try:
            config._client().decide_submission(resource, self.external_id, {
                'actor_nopeg': nopeg,
                'decision': decision,
                'level': self.approval_current_level,
            })
        except SaasClientError as exc:
            # Pesan server diteruskan apa adanya: ia yang tahu kenapa ditolak,
            # dan menyembunyikannya membuat tombol tampak tidak bekerja.
            raise UserError(_('Presenly refused this decision: %(error)s', error=exc)) from exc

        # Jendela tarikan disegarkan supaya keadaan barunya terlihat. Bukan hanya
        # baris ini: tarikan bekerja per jendela, dan menyempitkannya untuk satu
        # baris akan menjadi jalur kedua yang harus dijaga sama.
        config._pull_recent_data()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('Decision sent to Presenly. The request has been refreshed.'),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class PresenlySaasConfig(models.Model):
    """Setelan arah tulis untuk keputusan persetujuan."""

    _inherit = 'presenly.saas.config'

    allow_approval_from_odoo = fields.Boolean(
        string='Decide Requests from Odoo',
        default=False,
        help='Show approve and reject buttons on requests, and allow decisions to be '
             'sent to Presenly. Off by default: a decision is a decision, wherever it '
             'is taken, and this one leaves the application.',
    )
