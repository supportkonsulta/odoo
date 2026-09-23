import hashlib
import hmac
import json
import logging
import time

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Toleransi terhadap cap waktu pengirim. Permintaan yang lebih tua dari ini
# ditolak, supaya panggilan lama tidak bisa dipakai ulang.
SIGNATURE_TOLERANCE_SECONDS = 300


class PresenlySaasWebhook(http.Controller):
    """Penerima pemberitahuan perubahan pegawai dari server Presenly.

    Dipakai untuk arah yang tidak bisa dijangkau Odoo sendiri: server Presenly
    belum bisa memberi tahu Odoo, jadi selama ini arah itu harus diambil dengan
    polling. Dengan webhook ini, perubahan di Presenly langsung sampai.

    Dua lapis pengamanan, dan keduanya diperlukan:

    1. **Token di dalam alamat.** Tanpa ini, siapa pun yang tahu path-nya bisa
       memicu sinkronisasi berulang kali.
    2. **Tanda tangan HMAC-SHA256 atas `<cap waktu>.<badan permintaan>`.**
       Token hanya membuktikan pemanggil tahu alamatnya; tanda tangan
       membuktikan pemanggil memegang rahasianya, dan badannya tidak diubah di
       tengah jalan.

    Yang diterima hanya **penanda**, bukan data pegawai. Datanya diambil Odoo
    sendiri lewat API yang terautentikasi, sehingga tidak ada PII yang masuk
    lewat jalur publik ini, dan isinya tidak pernah bisa basi.
    """

    @http.route(
        '/presenly_saas/webhook/<string:token>',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def employee_webhook(self, token, **_kwargs):
        raw_body = request.httprequest.get_data(as_text=True) or ''
        config = self._config_for_token(token)
        if not config:
            # Token tidak dikenal dan webhook dimatikan dijawab sama, supaya
            # tidak ada cara mengetahui token mana yang pernah ada.
            return self._json(404, {'error': 'not_found'})

        timestamp = request.httprequest.headers.get('X-Presenly-Timestamp', '')
        signature = request.httprequest.headers.get('X-Presenly-Signature', '')
        if not self._signature_is_valid(config, timestamp, raw_body, signature):
            _logger.warning(
                "Presenly SaaS: webhook rejected for company %s — signature or "
                "timestamp did not check out.",
                config.company_id.display_name,
            )
            return self._json(401, {'error': 'invalid_signature'})

        try:
            payload = json.loads(raw_body) if raw_body else {}
        except ValueError:
            return self._json(400, {'error': 'invalid_json'})

        event = payload.get('event') or request.httprequest.headers.get('X-Presenly-Event')
        nopeg = payload.get('nopeg')

        if event == 'test.ping':
            # Panggilan uji dari tombol Register: dijawab tanpa menarik apa pun.
            # Sampai di sini berarti alamatnya terjangkau, tanda tangannya cocok,
            # dan tokennya benar — itu saja yang dibuktikan panggilan ini.
            config.sudo().write({'webhook_last_received_at': fields_now()})
            return self._json(200, {'received': True, 'test': True})

        try:
            ringkas, error, ditangani = self._pull_for_event(config, event)
        except Exception as exc:  # noqa: BLE001 - dijawab 500 supaya pengirim mencoba lagi
            _logger.exception("Presenly SaaS: webhook sync failed: %s", exc)
            return self._json(500, {'error': 'sync_failed'})

        if error:
            _logger.warning("Presenly SaaS: webhook sync reported: %s", error)
            return self._json(500, {'error': 'sync_failed', 'detail': error})

        config.sudo().write({'webhook_last_received_at': fields_now()})
        push = ringkas.get('push') or {}
        return self._json(200, {
            'received': True,
            'event': event,
            'handled': ditangani,
            'pulled': ringkas.get('pulled', 0),
            'nopeg': nopeg,
            'created': ringkas.get('created', 0),
            'updated': ringkas.get('updated', 0),
            'pushed': push.get('pushed', 0),
        })

    def _pull_for_event(self, config, event):
        """Tarik hanya yang berubah, sesuai peristiwa yang datang.

        Mengembalikan ``(ringkasan, error, sumber)``. Sebelumnya semua peristiwa
        menarik pegawai, sehingga perubahan klien pun memicu penarikan pegawai
        yang tidak ada hubungannya — dan perubahan lokasi kerja tidak pernah
        tersalin ke `hr.work.location` sampai cron berjalan.
        """
        nama = event or ''
        if nama.startswith('client.'):
            ringkas, error = config._pull_clients()
            return ringkas, error, 'clients'
        if nama.startswith('work_location.'):
            # Cermin acuan diganti sekaligus, dan penyalinan ke `hr.work.location`
            # ikut berjalan di dalamnya bila setelannya menyala.
            ringkas, error = config._pull_reference_data()
            return ringkas, error, 'work_locations'
        # Pegawai juga menjadi jalur untuk peristiwa tanpa nama (pengirim lama)
        # dan untuk nama yang belum dikenal: itu tarikan yang paling penting.
        ringkas, error = config._pull_employees()
        return ringkas, error, 'employees'

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------
    def _config_for_token(self, token):
        return request.env['presenly.saas.config']._find_by_webhook_token(token) or None

    def _signature_is_valid(self, config, timestamp, raw_body, signature):
        if not config.webhook_secret or not signature:
            return False
        try:
            selisih = abs(time.time() - float(timestamp))
        except (TypeError, ValueError):
            return False
        if selisih > SIGNATURE_TOLERANCE_SECONDS:
            return False

        expected = hmac.new(
            config.webhook_secret.encode('utf-8'),
            ('%s.%s' % (timestamp, raw_body)).encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        diberikan = signature.split('=', 1)[-1].strip()
        # Perbandingan waktu-tetap: perbandingan biasa membocorkan berapa
        # karakter awal yang sudah benar.
        return hmac.compare_digest(expected, diberikan)

    @staticmethod
    def _json(status, payload):
        return request.make_json_response(payload, status=status)


def fields_now():
    """Dipisah agar mudah diganti di tes."""
    from odoo import fields
    return fields.Datetime.now()
