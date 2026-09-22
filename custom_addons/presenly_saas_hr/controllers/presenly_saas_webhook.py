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

        try:
            summary, error = config._pull_employees()
        except Exception as exc:  # noqa: BLE001 - dijawab 500 supaya pengirim mencoba lagi
            _logger.exception("Presenly SaaS: webhook sync failed: %s", exc)
            return self._json(500, {'error': 'sync_failed'})

        if error:
            _logger.warning("Presenly SaaS: webhook sync reported: %s", error)
            return self._json(500, {'error': 'sync_failed', 'detail': error})

        config.sudo().write({'webhook_last_received_at': fields_now()})
        push = summary.get('push') or {}
        return self._json(200, {
            'received': True,
            'event': event,
            'nopeg': nopeg,
            'pulled': summary.get('pulled', 0),
            'created': summary.get('created', 0),
            'updated': summary.get('updated', 0),
            'pushed': push.get('pushed', 0),
        })

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
