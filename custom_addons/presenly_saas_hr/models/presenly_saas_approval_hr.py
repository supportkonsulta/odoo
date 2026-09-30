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
#
# Namanya persis sama dengan nama resource di tarikan, dan backend harus melayani
# keputusan untuk semuanya sebelum tombolnya dinyalakan di sini: tombol yang muncul
# padahal endpoint-nya belum ada menghasilkan penolakan yang membingungkan.
# Kelimanya sudah dilayani (`POST /v1/submissions/{resource}/{id}/decision`).
#
# SPPD belum ada di daftar ini karena belum ikut dicerminkan modul sama sekali.
RESOURCE_BY_MODEL = {
    'presenly.saas.leave': 'leaves',
    'presenly.saas.overtime': 'overtimes',
    'presenly.saas.medical.certificate': 'medical-certificates',
    'presenly.saas.attendance.correction': 'attendance-corrections',
    'presenly.saas.shift.swap': 'shift-swaps',
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
    presenly_decide_hint = fields.Char(
        string='Decision Note',
        compute='_compute_presenly_approver',
        help='Why a decision cannot be sent from here, filled only for the user '
             'who may send it. Empty means nothing stands in the way.',
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
        # Dua syarat yang tidak terlihat dari barisnya, tetapi menentukan apakah
        # tombolnya berguna: keputusan harus diizinkan pada koneksinya, dan
        # pengguna yang menekannya harus punya nopeg. Tombol yang muncul lalu
        # ditolak lebih buruk daripada tombol yang tidak muncul dengan alasannya.
        config = self.env['presenly.saas.config'].sudo()._config_for_company(
            self.env.company,
        )
        boleh_kirim = bool(config and config.allow_approval_from_odoo)
        nopeg = self.env.user.presenly_nopeg

        for pengajuan in self:
            pengguna = pengajuan._presenly_approver_user()
            bisa_diputuskan = pengajuan._presenly_resource() in RESOURCE_BY_MODEL.values()
            berhak = bool(pengguna) and pengguna == self.env.user

            pengajuan.presenly_odoo_approver_id = pengguna
            pengajuan.presenly_decidable = bisa_diputuskan
            pengajuan.presenly_can_decide = (
                berhak and bisa_diputuskan and boleh_kirim and bool(nopeg)
            )
            pengajuan.presenly_decide_hint = pengajuan._presenly_decide_hint(
                berhak, bisa_diputuskan, boleh_kirim, nopeg,
            )

    def _presenly_decide_hint(self, berhak, bisa_diputuskan, boleh_kirim, nopeg):
        """Alasan keputusan tidak bisa dikirim dari sini, untuk yang berhak.

        Pengguna lain tidak perlu penjelasan kenapa tombolnya tidak ada: yang
        dicari mereka bukan tombol itu.
        """
        self.ensure_one()
        if not berhak:
            return ''
        if not bisa_diputuskan:
            return _('This request type cannot be decided from Odoo yet.')
        if not boleh_kirim:
            return _('Deciding requests from Odoo is turned off for this connection. '
                     'Turn on "Decide Requests from Odoo" first.')
        if not nopeg:
            return _('Your Odoo user has no Presenly nopeg yet, and Presenly identifies '
                     'who decided by the nopeg. Fill in the Presenly Nopeg on your '
                     'employee record first.')
        return ''

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

    def _presenly_actor_nopeg(self):
        """Nopeg pengguna yang sedang menekan tombol keputusan.

        Dibaca dari `res.users.presenly_nopeg`, **bukan** lewat
        `user.employee_id.presenly_nopeg`. `employee_id` adalah pegawai pada
        perusahaan yang sedang aktif (`addons/hr/models/res_users.py`),
        sedangkan record pegawai di sini berada di perusahaan integrasi. Pegawai
        cabang - yang perusahaan aktifnya perusahaan cabang - karena itu dicap
        "belum tertaut nopeg" walaupun nopegnya sudah terisi, dan itulah satu-
        satunya yang menghalanginya memutuskan pengajuan dari Odoo.
        """
        return self.env.user.presenly_nopeg or ''

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

        # Salinan kita bisa tertinggal: keputusan level sebelumnya bisa diambil
        # dari aplikasi, sedangkan pemberitahuan perubahannya tidak selalu sampai
        # ke sini. Menyegarkan lebih dulu lalu membaca ulang levelnya membuat
        # keputusan dikirim dengan level yang benar - mengirim level yang basi
        # hanya menghasilkan penolakan yang membingungkan.
        config._refresh_recent_from_decision()
        self.invalidate_recordset(
            ['approval_current_level', 'approval_step_ids', 'status',
             'presenly_odoo_approver_id'],
        )

        # Setelah disegarkan, mungkin tidak ada lagi yang menunggu diputuskan:
        # level terakhirnya sudah diputuskan orang lain. Itu bukan galat, hanya
        # keadaan yang sudah berubah - dan yang dibutuhkan pengguna adalah layar
        # yang menampilkan keadaannya, bukan pesan untuk memuat ulang sendiri.
        if not self.approval_current_level:
            return self._presenly_notice(_(
                'This request is no longer waiting for a decision. The screen has '
                'been refreshed.'
            ))

        nopeg = self._presenly_actor_nopeg()
        if not nopeg:
            raise UserError(_(
                'Your Odoo user is not linked to a Presenly nopeg. Ask for the nopeg '
                'to be filled in on your employee record first, because Presenly '
                'identifies who decided by the nopeg.'
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
            # Ditolak berarti salinan kita yang tertinggal, jadi disegarkan lagi
            # lalu pesannya dikembalikan sebagai pemberitahuan - bukan galat.
            #
            # Perbedaan itu bukan soal gaya: pemberitahuan bisa membawa aksi muat
            # ulang, sedangkan `UserError` tidak. Dan `UserError` juga membatalkan
            # transaksi yang sedang berjalan, jadi penyegaran yang ditulis di
            # transaksi ini akan ikut hilang bersama pesannya.
            error_tarik = config._refresh_recent_from_decision()
            catatan = ''
            if error_tarik:
                catatan = _(' The refresh failed too: %(error)s', error=error_tarik)
            return self._presenly_notice(_(
                'Presenly refused this decision: %(error)s%(catatan)s',
                error=exc, catatan=catatan,
            ), tipe='warning')

        # Jendela tarikan disegarkan supaya keadaan barunya terlihat. Bukan hanya
        # baris ini: tarikan bekerja per jendela, dan menyempitkannya untuk satu
        # baris akan menjadi jalur kedua yang harus dijaga sama.
        #
        # Kegagalannya **dilaporkan**, bukan ditelan. Kalau tarikannya gagal,
        # layarnya akan tetap menunjukkan keadaan lama setelah dimuat ulang - dan
        # tanpa pesan, itu terbaca sebagai "keputusannya tidak berpengaruh".
        _ringkas, error_tarik = config._pull_recent_data()

        catatan = ''
        if error_tarik:
            _logger.warning(
                'Presenly SaaS: keputusan terkirim, tetapi penyegarannya gagal: %s',
                error_tarik,
            )
            catatan = _(' The refresh failed, so this screen may still show the old '
                        'state: %(error)s', error=error_tarik)

        # Keputusannya terkirim, tetapi layarnya tidak bisa dipastikan benar:
        # itu galat, bukan kabar baik.
        return self._presenly_notice(
            _('Decision sent to Presenly.%(catatan)s', catatan=catatan),
            tipe='error' if error_tarik else 'alert',
        )

    def _presenly_notice(self, message, tipe='alert'):
        """Pemberitahuan sebagai dialog bawaan Odoo, sesuai tingkatannya.

        Dialog, bukan toast: pesan yang menjelaskan kenapa sebuah keputusan
        ditolak harus bisa dibaca sampai selesai, dan toast menghilang sendiri.

        Layarnya tidak dimuat ulang sendiri, melainkan lewat tombol di dialognya:
        pengguna bisa sedang menyunting hal lain di layar yang sama, dan memuat
        ulang tanpa izin berarti membuang isian itu.
        """
        return {
            'type': 'ir.actions.client',
            'tag': 'presenly_saas.notice',
            'params': {
                'title': _('Decision on this request') if tipe != 'alert'
                         else _('Decision sent'),
                'body': message,
                # Tingkatannya dipetakan ke dialog bawaan Odoo di sisi klien:
                # `alert`, `warning`, dan `error`.
                'kind': tipe,
                # Layarnya disegarkan supaya tombol yang sudah tidak berhak tidak
                # tertinggal di layar.
                'reload': True,
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
