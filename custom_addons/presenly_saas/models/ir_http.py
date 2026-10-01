import logging

from werkzeug.exceptions import abort

from odoo import models
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# Halaman yang dituju saat backend ditutup. Konstanta ini juga dipakai
# pengendalinya, supaya jalurnya hanya ditulis di satu tempat.
BLOCKED_PATH = '/presenly_saas/blocked'


class IrHttp(models.AbstractModel):
    """Gerbang langganan di jalur masuk semua permintaan.

    Ini pembalikan batasan arsitektur yang disengaja, dan alasannya perlu
    terbaca di sini: modul ini dulu tidak menyentuh apa pun milik Odoo, sehingga
    penegakan langganan hanya bisa berupa kontrak yang harus dipanggil modul
    lain. Kontrak itu tidak pernah dipanggil, jadi langganan yang hangus tidak
    menutup apa pun. Satu gerbang di sini menutup semuanya sekaligus: webclient,
    `/web/dataset/call_kw`, laporan, API aplikasi, dan panggilan dengan kunci
    API.

    Yang di-inherit adalah `ir.http`, yaitu infrastruktur permintaan, bukan
    model bisnis, dan tidak ada berkas di addon `presenly` yang disentuh.

    `_pre_dispatch` dipilih karena ia berjalan setelah autentikasi (jadi
    pengguna dan perusahaannya sudah diketahui) dan sebelum controller (jadi
    tidak ada efek samping yang perlu dibatalkan). Nilai kembaliannya tidak
    dipakai Odoo, jadi penolakannya lewat pengecualian:

    - rute `http` (navigasi) dialihkan ke halaman blokir: pengguna melihat
      penjelasan, bukan galat mentah;
    - rute `jsonrpc` (klien API, tab yang masih terbuka) mendapat galat JSON-RPC
      yang membawa alasan yang sama.

    Seluruh badannya dibungkus satu penjaga: gerbang yang gagal tidak boleh
    mengubah dirinya menjadi backend yang mati.
    """

    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        cls._presenly_saas_gate(rule)

    @classmethod
    def _presenly_saas_gate(cls, rule):
        try:
            guard = request.env['presenly.saas.guard']
            reason = guard.request_block_reason(
                request.httprequest.path, requester=cls._presenly_saas_user()
            )
        except Exception:  # noqa: BLE001 - gagal terbuka, bukan gagal tertutup
            _logger.exception(
                "Presenly SaaS: subscription gate failed, letting the request "
                "through"
            )
            return

        if not reason:
            return

        if rule.endpoint.routing.get('type', 'http') == 'http':
            _logger.info(
                "Presenly SaaS: refused %s (%s)",
                request.httprequest.path, reason,
            )
            abort(request.redirect(BLOCKED_PATH))

        raise UserError(guard.block_message(reason))

    @classmethod
    def _presenly_saas_user(cls):
        """Pengguna di balik permintaan ini, termasuk pada rute `auth='none'`.

        Kerangka backend (`/odoo`) dan beranda (`/`) memakai `auth='none'` dan
        memasang penggunanya belakangan, jadi `request.env.uid` kosong di sini
        walaupun sesinya milik seseorang. Membaca `session.uid` membuat gerbang
        tetap menutup kerangka backend; itu justru permukaan yang paling perlu
        ditutup, karena di dalamnya ada menu dan seluruh bundel aplikasi.
        """
        uid = request.env.uid or request.session.uid
        if not uid:
            return None
        return request.env['res.users'].sudo().browse(uid)
