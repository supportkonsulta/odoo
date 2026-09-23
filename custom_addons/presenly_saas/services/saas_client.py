"""HTTP client for the Presenly SaaS control plane.

Only one endpoint is consumed: ``GET /api/external/v1/subscription``. It is
guarded on the server side by ``X-API-Key`` and a mandatory ``X-Tenant-ID``.

The client takes plain primitives instead of a recordset so it can be unit
tested without an Odoo environment. It holds no cache and no global state, it
never retries an authentication failure, and it never writes the API key into
a log line or an exception message.
"""

import logging
import time
from urllib.parse import quote

import requests

_logger = logging.getLogger(__name__)

USER_AGENT = "presenly-saas-odoo"

SUPPORTED_SCHEMA_VERSIONS = ("1.0.0",)


def redact(text, secret):
    """Return ``text`` with ``secret`` replaced, so credentials never leak."""
    text = str(text)
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


class SaasClientError(Exception):
    """Raised for every failure mode of the SaaS client.

    Attributes:
        code: machine readable reason (``NETWORK_ERROR``, ``UNAUTHORIZED``,
            ``RATE_LIMITED``, ``BAD_PAYLOAD``, ``HTTP_ERROR``).
        http_status: HTTP status code when a response was received.
    """

    def __init__(self, message, code=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class PresenlySaasClient:
    def __init__(self, base_url, api_key, tenant_code, timeout=10, retry_count=2):
        self.base_url = (base_url or "").strip()
        self.api_key = api_key or ""
        self.tenant_code = tenant_code or ""
        self.timeout = timeout or 10
        self.retry_count = max(0, retry_count or 0)

    # ------------------------------------------------------------------
    # URL & headers
    # ------------------------------------------------------------------
    def _endpoint(self, path):
        base = self.base_url.rstrip("/")
        if base.endswith("/api"):
            base = base[: -len("/api")]
        return f"{base}/api/external{path}"

    @staticmethod
    def _clean_params(params):
        """Buang parameter kosong; kirim hanya yang benar-benar diisi."""
        if not params:
            return None
        return {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }

    def _headers(self):
        return {
            "X-API-Key": self.api_key,
            "X-Tenant-ID": self.tenant_code,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_subscription(self):
        """Return the ``data`` object of the subscription endpoint."""
        return self.get_envelope("/v1/subscription")["data"]

    def get_attendance_logs(self, params=None):
        """Log presensi sesi. Mengembalikan ``{"data": [...], "meta": {...}}``."""
        return self.get_envelope("/v1/presenly/attendance-logs", params)

    def get_changes(self, since=None):
        """Waktu perubahan terakhir tiap jenis data, tanpa menarik datanya.

        Satu permintaan murah untuk menjawab "ada yang berubah?", dipakai setiap
        kali halaman cermin dibuka.
        """
        params = {'since': since} if since else None
        return self.get_envelope("/v1/presenly/changes", params)

    def download_file(self, path):
        """Isi sebuah berkas unggahan, dalam byte.

        Berkasnya selalu pribadi, jadi `include_pii=true` ikut dikirim — sama
        seperti kolom PII lain di API ini.
        """
        return self._request(
            'GET', '/v1/files/download',
            params={'path': path, 'include_pii': 'true'},
            raw=True,
        )

    def get_attendance_recap(self, params=None):
        """Rekap presensi per pegawai per bulan."""
        return self.get_envelope("/v1/presenly/attendance-recap", params)

    def get_resource(self, resource, params=None):
        """Ambil satu resource referensi, mis. ``work-locations``."""
        return self.get_envelope("/v1/%s" % resource, params)

    def get_envelope(self, path, params=None):
        """Ambil seluruh amplop respons: ``{"data": ..., "meta": ...}``.

        Endpoint daftar memakai `meta` untuk paginasi. Membuang `meta` seperti
        pada endpoint langganan akan membuat pemanggil tidak tahu masih ada
        halaman berikutnya.
        """
        return self._get(path, params)

    def create_employee(self, payload):
        """Buat pegawai di Presenly. Mengembalikan amplop respons."""
        return self._request('POST', '/v1/employees', body=payload)

    def update_employee(self, nopeg, payload):
        """Perbarui sebagian kolom pegawai. Hanya kolom yang dikirim yang ditulis."""
        return self._request('PATCH', '/v1/employees/%s' % quote(nopeg, safe=''), body=payload)

    def update_work_location(self, location_id, payload):
        """Perbarui sebagian kolom lokasi kerja. Hanya kolom yang dikirim yang ditulis.

        Endpoint-nya menolak lokasi yang belum ada: pembuatan lokasi tetap
        dilakukan dari aplikasi, karena di sanalah lokasi ditetapkan ke klien dan
        proyek.
        """
        return self._request(
            'PATCH', '/v1/work-locations/%d' % int(location_id), body=payload
        )

    def get_work_location_write_contract(self):
        """Kolom lokasi kerja yang boleh ditulis dari luar, menurut server."""
        return self._request('GET', '/v1/work-locations/writable-fields')['data']

    def decide_submission(self, resource, submission_id, payload):
        """Putuskan satu pengajuan: setuju atau tolak, pada level yang berjalan.

        Aktornya disebutkan di badan permintaan karena satu kunci API mewakili
        tenant, bukan orang. Haknya tetap diperiksa server.
        """
        return self._request(
            'POST',
            '/v1/submissions/%s/%d/decision' % (resource, int(submission_id)),
            body=payload,
        )

    def get_approval_contract(self):
        """Kontrak keputusan persetujuan menurut server."""
        return self._request('GET', '/v1/approvals/contract')['data']

    def register_webhook(self, payload):
        """Daftarkan alamat penerima webhook milik instalasi ini."""
        return self._request('PUT', '/v1/webhooks', body=payload)

    def unregister_webhook(self):
        """Matikan pengiriman webhook ke instalasi ini, tanpa menghapus riwayatnya."""
        return self._request('DELETE', '/v1/webhooks')

    def get_webhook_deliveries(self, params=None):
        """Riwayat pengiriman di sisi server, untuk memeriksa kesehatan tujuan."""
        return self._request('GET', '/v1/webhooks/deliveries', params=params)

    def get_employee_write_contract(self):
        """Kolom pegawai yang boleh ditulis dari luar, menurut server."""
        return self._request('GET', '/v1/employees/writable-fields')['data']

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _get(self, path, params=None):
        return self._request('GET', path, params=params)

    def _request(self, method, path, params=None, body=None, raw=False):
        """Satu implementasi percobaan ulang untuk semua metode.

        Percobaan ulang **tidak** dilakukan untuk galat 4xx: permintaan yang
        ditolak karena datanya salah akan ditolak lagi, dan mengulanginya hanya
        memperlambat tanpa mengubah hasil.
        """
        url = self._endpoint(path)
        attempts = self.retry_count + 1

        for attempt in range(attempts):
            last_attempt = attempt + 1 >= attempts
            started = time.monotonic()
            try:
                response = requests.request(
                    method,
                    url,
                    headers=dict(self._headers(), **({'Content-Type': 'application/json'} if body is not None else {})),
                    params=self._clean_params(params),
                    json=body,
                    timeout=self.timeout,
                    verify=True,
                )
            except requests.RequestException as exc:
                _logger.info(
                    "Presenly SaaS request to %s failed (attempt %s/%s): %s",
                    url,
                    attempt + 1,
                    attempts,
                    redact(exc, self.api_key),
                )
                if not last_attempt:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise SaasClientError(
                    "Tidak dapat menghubungi server Presenly SaaS.",
                    code="NETWORK_ERROR",
                ) from exc

            duration_ms = int((time.monotonic() - started) * 1000)
            _logger.info(
                "Presenly SaaS %s -> HTTP %s (%s ms)",
                url,
                response.status_code,
                duration_ms,
            )

            if response.status_code >= 500 and not last_attempt:
                time.sleep(0.5 * (2**attempt))
                continue

            if raw:
                # Unduhan berkas: isinya byte, bukan amplop JSON.
                return response.content
            return self._parse_response(response)

        # Unreachable: the loop either returns or raises.
        raise SaasClientError(
            "Tidak dapat menghubungi server Presenly SaaS.",
            code="NETWORK_ERROR",
        )

    def _parse_response(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code == 401:
            raise SaasClientError(
                "API key ditolak oleh server Presenly SaaS.",
                code="UNAUTHORIZED",
                http_status=401,
            )

        if response.status_code >= 400:
            message = payload.get("message") if isinstance(payload, dict) else None
            code = payload.get("code") if isinstance(payload, dict) else None
            raise SaasClientError(
                message
                or f"Server Presenly SaaS menolak permintaan (HTTP {response.status_code}).",
                code=code or "HTTP_ERROR",
                http_status=response.status_code,
            )

        if not isinstance(payload, dict) or not payload.get("success"):
            message = payload.get("message") if isinstance(payload, dict) else None
            raise SaasClientError(
                message or "Respons server Presenly SaaS tidak dikenali.",
                code="BAD_PAYLOAD",
                http_status=response.status_code,
            )

        data = payload.get("data")
        meta = payload.get("meta") or {}
        # Versi skema bisa ada di dalam data (endpoint langganan) atau di meta
        # (endpoint daftar). Keduanya diterima.
        self._validate_schema(meta if meta.get("schema_version") else (data or {}))
        return {"data": data, "meta": meta}

    def _validate_schema(self, data):
        version = data.get("schema_version")
        if version and version not in SUPPORTED_SCHEMA_VERSIONS:
            raise SaasClientError(
                f"Versi skema respons Presenly SaaS tidak didukung: {version}.",
                code="UNSUPPORTED_SCHEMA",
            )
