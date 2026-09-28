import logging

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.ir_http import BLOCKED_PATH

_logger = logging.getLogger(__name__)

REFRESH_PATH = BLOCKED_PATH + '/refresh'
REPAIR_PATH = BLOCKED_PATH + '/repair'
MANAGER_GROUP = 'presenly_saas.group_presenly_saas_manager'


class PresenlySaasBlocked(http.Controller):
    """Halaman yang menjelaskan, dan dua jalan keluar untuk manajer.

    Halaman ini satu-satunya permukaan backend yang tetap hidup saat akses
    ditutup, jadi isinya harus menjawab lengkap: kenapa ditutup, sejak kapan,
    dan apa yang bisa dilakukan sekarang. Tidak ada rahasia di sini: kunci API
    tidak pernah dirender, dan kolomnya dikosongkan, bukan diisi.

    Dua jalan keluar itu sengaja sempit:

    - **Refresh subscription** untuk kasus yang paling sering, yaitu server sudah
      memperpanjang tetapi Odoo masih memegang jawaban lama;
    - **Perbaiki koneksi** untuk kasus yang lebih jarang tetapi mematikan, yaitu
      alamat atau kunci API berubah sehingga penyegaran tidak mungkin berhasil.

    Keduanya hanya hidup saat akses memang ditutup. Begitu langganannya sehat,
    rutenya mengalihkan ke backend, jadi ia bukan pintu belakang.
    """

    # ------------------------------------------------------------------
    # Halaman
    # ------------------------------------------------------------------
    @http.route(BLOCKED_PATH, type='http', auth='user', website=False, readonly=True)
    def blocked_page(self, **kw):
        return self._page()

    # ------------------------------------------------------------------
    # Jalan keluar
    # ------------------------------------------------------------------
    # Rutenya sengaja setipis ini: seluruh keputusannya ada di method biasa,
    # supaya bisa diuji tanpa server. Cabang "staf ditolak", misalnya, tidak
    # bisa dijangkau lewat HTTP tanpa token CSRF milik sesi staf sendiri.
    @http.route(REFRESH_PATH, type='http', auth='user', methods=['POST'], website=False)
    def blocked_refresh(self, **kw):
        return self._refresh()

    @http.route(REPAIR_PATH, type='http', auth='user', methods=['POST'], website=False)
    def blocked_repair(self, base_url=None, tenant_code=None, api_key=None, **kw):
        return self._repair(base_url, tenant_code, api_key)

    # ------------------------------------------------------------------
    # Isi
    # ------------------------------------------------------------------
    def _page(self):
        guard = request.env['presenly.saas.guard']
        if not guard.block_reason():
            return request.redirect('/odoo')
        return request.render(
            'presenly_saas.blocked_page', guard.blocked_page_values()
        )

    def _refresh(self):
        guard = request.env['presenly.saas.guard']
        if not guard.block_reason():
            return request.redirect('/odoo')
        if not self._is_manager():
            return self._render(guard, error=_(
                "Only a Presenly SaaS manager can refresh the subscription here."
            ))

        config = request.env['presenly.saas.config'].sudo()._get_or_create(
            request.env.company
        )
        error = self._fetch(config)
        if error:
            return self._render(guard, error=error)

        # Jawaban baru bisa saja belum mengubah apa pun: langganan yang memang
        # masih hangus tetap hangus. Yang berubah hanya kepercayaannya, jadi
        # halamannya tetap tampil, dengan keterangan apa adanya.
        if guard.block_reason():
            return self._render(guard, message=_(
                "The Presenly server answered, and the subscription is still "
                "not active."
            ))
        return request.redirect('/odoo')

    def _repair(self, base_url=None, tenant_code=None, api_key=None):
        guard = request.env['presenly.saas.guard']
        if not guard.block_reason():
            return request.redirect('/odoo')
        if not self._is_manager():
            return self._render(guard, error=_(
                "Only a Presenly SaaS manager can change the connection here."
            ))

        config = request.env['presenly.saas.config'].sudo()._get_or_create(
            request.env.company
        )
        values = {}
        if base_url is not None:
            values['base_url'] = (base_url or '').strip() or False
        if tenant_code is not None:
            values['tenant_code'] = (tenant_code or '').strip() or False
        # Kolom kunci API selalu kosong saat dirender. Kosong berarti "jangan
        # ubah", bukan "hapus": kunci yang sedang dipakai tidak boleh terhapus
        # oleh halaman perbaikan yang tidak menampilkannya.
        if api_key:
            values['api_key'] = api_key.strip()
        config.write(values)

        error = self._fetch(config)
        if error:
            return self._render(guard, error=error)
        if guard.block_reason():
            return self._render(guard, message=_(
                "The connection is saved, and the subscription is still not "
                "active."
            ))
        return request.redirect('/odoo')

    # ------------------------------------------------------------------
    # Bantu
    # ------------------------------------------------------------------
    def _is_manager(self):
        return request.env.user.has_group(MANAGER_GROUP)

    def _render(self, guard, error=None, message=None):
        return request.render(
            'presenly_saas.blocked_page',
            guard.blocked_page_values(error=error, message=message),
        )

    def _fetch(self, config):
        """Segarkan langganan, dan kembalikan pesan galatnya bila gagal.

        Galat dikembalikan sebagai nilai, bukan dinaikkan: halaman blokir harus
        tetap tampil walaupun penyegarannya gagal, karena justru itu keadaannya.
        """
        try:
            _subscription, error = config._fetch_and_store(log=True)
        except UserError as exc:
            return str(exc)
        return error
