import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_datetime

_logger = logging.getLogger(__name__)

SKIP_CONTEXT_KEY = 'presenly_saas_skip_guard'

# Sekoci terakhir. Dibaca dari `ir.config_parameter` supaya bisa dibalik tanpa
# memuat halaman apa pun: satu baris di `odoo-bin shell` atau di psql, dan
# gerbangnya berhenti menutup. Namanya sengaja berbentuk "matikan blokir",
# bukan "nyalakan akses", supaya nilai yang salah tulis tidak membuka apa pun.
FORCE_ALLOW_PARAM = 'presenly_saas_block_disabled'

# Jalur yang tetap hidup saat langganan diblokir. Diperiksa SEBELUM menyentuh
# basis data, jadi permintaan aset tidak menambah satu query pun.
#
# Isinya sengaja sesempit ini: masuk dan keluar, aset yang dipakai halaman
# blokir, logo, halaman blokir beserta rute perbaikannya, dan penerima webhook.
# Yang tidak ada di sini ikut ditutup, termasuk seluruh backend, laporan, dan
# API aplikasi.
ALLOWED_PATH_PREFIXES = (
    '/web/assets/',
    '/web/static/',
    '/web/login',
    '/web/session/',
    '/web/manifest.webmanifest',
    '/web/binary/company_logo',
    '/logo',
    '/favicon.ico',
    '/presenly_saas/blocked',
    '/presenly_saas/webhook/',
)


def decide_block(facts, now):
    """Alasan blokir menurut fakta, atau ``False``.

    Sengaja fungsi murni: tanpa basis data, tanpa waktu implisit, dan tanpa
    mode. Mode penegakan adalah kebijakan, dan kebijakan itu dipasang oleh
    pemanggilnya. Itu yang membuat seluruh matriksnya bisa diuji tanpa HTTP dan
    tanpa menyiapkan satu record pun.

    Aturannya konservatif, sama seperti API guard: yang memblokir hanya jawaban
    nyata dari server. Snapshot yang tidak terkonfirmasi baru memblokir setelah
    tenggangnya lewat, dan hanya bila tenggangnya memang diisi.
    """
    if not facts:
        return False

    override_until = facts.get('override_until')
    if override_until and now < override_until:
        return False

    status = facts.get('status')
    source = facts.get('state_source')

    if source == 'live':
        if status in ('expired', 'suspended'):
            return status
        if status == 'trial' and facts.get('is_trial'):
            end = facts.get('trial_ends_at') or facts.get('current_period_end')
            if end and now > end:
                return 'trial_ended'
        # `active` dan `unknown` tidak pernah memblokir. Status ditentukan
        # server, dan modul ini tidak menghitung tanggal sendiri.
        return False

    # Pernah dapat jawaban, tetapi tidak lagi. Statusnya tidak berubah karena
    # kegagalan jaringan; yang berubah hanya kepercayaannya.
    grace = facts.get('grace_days') or 0
    last_sync = facts.get('last_sync_at')
    if grace and last_sync and now > last_sync + timedelta(days=grace):
        return 'unconfirmed'
    return False


class PresenlySaasGuard(models.AbstractModel):
    """Policy API for other modules, and the gate for this installation.

    Dua hal hidup di sini sejak penegakan dijalankan secara global:

    1. **API kebijakan** untuk modul lain (``check``, ``is_allowed``,
       ``has_feature``). Sifatnya kontrak: yang memblokir adalah pemanggilnya.
    2. **Gerbang permintaan** (``request_block_reason``), dipakai
       ``ir.http._pre_dispatch`` untuk menutup backend saat langganan hangus.
       Berkasnya sendiri tetap tidak menyentuh model bisnis native: yang
       dipakainya adalah `ir.http`, yaitu infrastruktur, bukan model bisnis.

    Pass ``presenly_saas_skip_guard=True`` in the context to let system
    operations (imports, migrations, internal crons) through. That context also
    turns the gate off, which is what keeps migrations and tests from locking
    themselves out.
    """

    _name = 'presenly.saas.guard'
    _description = 'Presenly SaaS Guard'

    # ------------------------------------------------------------------
    # Read-only state
    # ------------------------------------------------------------------
    @api.model
    def _subscription_snapshot(self):
        """Snapshot langganan company aktif, atau recordset kosong."""
        config = self.env['presenly.saas.config'].sudo()._get_or_create()
        return self.env['presenly.saas.subscription'].sudo().search(
            [('company_id', '=', config.company_id.id)], limit=1
        )

    @api.model
    def state(self):
        """Ringkasan keadaan langganan untuk company aktif."""
        config = self.env['presenly.saas.config'].sudo()._get_or_create()
        subscription = self._subscription_snapshot()

        if not subscription:
            blocked = self.block_reason(config.company_id)
            return {
                'enabled': config.enabled,
                'guard_mode': config.guard_mode,
                'block_mode': config.block_mode,
                'blocked': bool(blocked),
                'blocked_reason': blocked,
                'status': 'unknown',
                'state_source': 'unreachable',
                'effective_state': 'allowed',
                'has_snapshot': False,
                'days_remaining': 0,
                'seat_limit': 0,
                'seats_used': 0,
                'grace_until': False,
                'plan_name': False,
                'missing_features': [],
            }

        blocked = self.block_reason(config.company_id)
        return {
            'enabled': config.enabled,
            'guard_mode': config.guard_mode,
            'block_mode': config.block_mode,
            'blocked': bool(blocked),
            'blocked_reason': blocked,
            'status': subscription.status,
            'state_source': subscription.state_source,
            'effective_state': subscription._effective_state(),
            'has_snapshot': True,
            'days_remaining': subscription.days_remaining,
            'seat_limit': subscription.seat_limit,
            'seats_used': subscription.seats_used,
            'grace_until': subscription.grace_until,
            'plan_name': subscription.plan_name,
            'missing_features': sorted(subscription._missing_feature_codes()),
        }

    # ------------------------------------------------------------------
    # Facts behind the gate
    # ------------------------------------------------------------------
    @api.model
    def _read_config(self, company):
        """Konfigurasi satu perusahaan, dibaca saja.

        Tidak memakai ``_get_or_create()``: gerbang ini berjalan di setiap
        permintaan, dan permintaan tidak boleh menulis apa pun. Tidak ada
        konfigurasi berarti tidak ada langganan yang bisa hangus.
        """
        return self.env['presenly.saas.config'].sudo().search(
            [('company_id', '=', company.id)], limit=1
        )

    @api.model
    def _facts(self, company=None):
        """Fakta penegakan satu perusahaan: dua pembacaan berindeks, tanpa cache.

        Rencana awalnya menaruh hasil ini di `ormcache`. Itu dibatalkan setelah
        diperiksa: nama cache di Odoo 19 terbatas pada `_REGISTRY_CACHES`, dan
        membuang salah satunya ikut membuang cache view. Dua pembacaan berindeks
        per permintaan lebih murah daripada membuang cache inti Odoo setiap kali
        langganan disegarkan, dan lebih mudah dipercaya: tidak ada jawaban basi
        yang perlu diinvalidasi.

        Biayanya diukur di `tests/test_guard_gate.py`.
        """
        company = company or self.env.company
        config = self._read_config(company)
        if not config:
            return {}

        subscription = self.env['presenly.saas.subscription'].sudo().search(
            [('company_id', '=', company.id)], limit=1
        )
        return {
            'block_mode': config.block_mode,
            'grace_days': config.grace_days,
            'override_until': config.block_override_until,
            'status': subscription.status if subscription else False,
            'state_source': subscription.state_source if subscription else False,
            'is_trial': bool(subscription.is_trial) if subscription else False,
            'trial_ends_at': subscription.trial_ends_at if subscription else False,
            'current_period_end': (
                subscription.current_period_end if subscription else False
            ),
            'last_sync_at': subscription.last_sync_at if subscription else False,
            'dry_run_noted_at': config.dry_run_noted_at,
            'blocked_since': config.blocked_since,
        }

    @api.model
    def _force_allowed(self):
        """Sekoci terakhir dari ``ir.config_parameter``."""
        value = self.env['ir.config_parameter'].sudo().get_param(FORCE_ALLOW_PARAM, '')
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

    # ------------------------------------------------------------------
    # The gate
    # ------------------------------------------------------------------
    @api.model
    def block_reason(self, company=None):
        """Alasan langganan ini memblokir sekarang, atau ``False``."""
        if self.env.context.get(SKIP_CONTEXT_KEY) or self._force_allowed():
            return False
        facts = self._facts(company)
        if facts.get('block_mode') != 'enforce':
            return False
        return decide_block(facts, fields.Datetime.now())

    @api.model
    def is_blocked(self, company=None):
        return bool(self.block_reason(company))

    @api.model
    def block_message(self, reason):
        """Kalimat untuk klien yang tidak bisa melihat halaman."""
        return _(
            "Access to this Odoo is paused: the Presenly subscription is not "
            "active (reason: %(reason)s). A Presenly SaaS manager can refresh "
            "the subscription from the blocked page.",
            reason=self.reason_label(reason),
        )

    @api.model
    def reason_label(self, reason):
        labels = {
            'expired': _("the subscription has expired"),
            'suspended': _("the subscription is suspended"),
            'trial_ended': _("the trial period has ended"),
            'unconfirmed': _("the Presenly server could not be reached in time"),
        }
        return labels.get(reason, reason or _("unknown"))

    @api.model
    def _gate_company(self, requester=None):
        """Perusahaan yang diperiksa gerbang.

        Biasanya perusahaan yang sedang dipakai sesi ini, karena itu yang
        menentukan data mana yang sedang dilihat. Rute seperti `/odoo` memakai
        `auth='none'`, jadi di sana `env.company` bukan perusahaan pengguna
        melainkan perusahaan pertama basis data; untuk rute itu yang benar
        adalah perusahaan bawaan pengguna dari sesinya.
        """
        if self.env.uid is None and requester is not None:
            return requester.company_id or self.env.company
        return self.env.company

    @api.model
    def request_block_reason(self, path, requester=None):
        """Alasan permintaan pada ``path`` harus ditolak, atau ``False``.

        Urutannya dari yang paling murah: jalur, lalu sekoci, lalu fakta. Itu
        yang membuat permintaan aset dan halaman masuk tidak menambah query.

        ``requester`` diberikan pemanggilnya karena rute `auth='none'` (misalnya
        `/odoo`, yaitu kerangka backend) belum punya pengguna di `env` walaupun
        sesinya jelas milik seseorang. Tanpa itu, justru kerangka backend yang
        lolos.

        Parameternya bernama ``requester``, bukan ``user``, dan itu bukan
        kerapian: `odoo.tools.translate` menebak uid dari variabel lokal bernama
        `user` di tumpukan pemanggil, dan sebuah recordset di situ membuatnya
        gagal menghitung terjemahan. Nama itu sudah menggigit sekali di tes.
        """
        if not path or path.startswith(ALLOWED_PATH_PREFIXES):
            return False
        if self.env.context.get(SKIP_CONTEXT_KEY) or self._force_allowed():
            return False

        requester = requester or self.env.user
        if not requester or requester.id == SUPERUSER_ID:
            # Tanpa pengguna: halaman masuk dan situs publik. uid 1: sekoci
            # pemulihan darurat, dan sengaja tidak ikut ditutup.
            return False
        if not requester.has_group('base.group_user'):
            # Portal dan publik bukan pemakai layanan berlangganan. Menutup
            # situs publik berarti membuat gangguan sendiri.
            return False

        company = self._gate_company(requester)
        facts = self._facts(company)
        mode = facts.get('block_mode')
        if mode == 'dry_run':
            # Uji coba: hitung yang AKAN diblokir, lalu tetap loloskan.
            if decide_block(facts, fields.Datetime.now()):
                self._note_dry_run(company)
            return False
        if mode != 'enforce':
            return False

        reason = decide_block(facts, fields.Datetime.now())
        if reason:
            self.note_block_started(reason, company)
        return reason

    # ------------------------------------------------------------------
    # Recording, kept rare on purpose
    # ------------------------------------------------------------------
    @api.model
    def _note_dry_run(self, company=None):
        """Hitung permintaan yang AKAN diblokir, paling banyak sekali semenit.

        Satu tulisan per permintaan akan menjadikan mode uji coba lebih berat
        daripada penegakannya sendiri, dan mengubah uji coba menjadi beban.
        """
        company = company or self.env.company
        facts = self._facts(company)
        now = fields.Datetime.now()
        noted = facts.get('dry_run_noted_at')
        if noted and (now - noted) < timedelta(minutes=1):
            return
        self._write_operational({
            'dry_run_blocked_count': (
                (self._read_config(company).dry_run_blocked_count or 0) + 1
            ),
            'dry_run_noted_at': now,
        }, company)

    @api.model
    def note_block_started(self, reason=None, company=None):
        """Catat kapan blokir mulai, sekali saja, untuk halaman blokir.

        Perusahaannya diterima dari pemanggilnya, bukan dibaca dari `env`:
        rute `auth='none'` tidak punya perusahaan di `env`, jadi membaca dari
        situ mencatat `False` pada justru permintaan yang paling sering ditolak.
        """
        company = company or self.env.company
        if not company:
            return
        if self._facts(company).get('blocked_since'):
            return
        self._write_operational({'blocked_since': fields.Datetime.now()}, company)
        _logger.warning(
            "Presenly SaaS: access blocked for company %s (%s)",
            company.display_name, reason or self.block_reason(company),
        )

    @api.model
    def _write_operational(self, values, company=None):
        """Tulis nilai operasional, dan jangan pernah gagalkan permintaan.

        Banyak rute Odoo memakai kursor hanya-baca. Pencatatan bukan alasan
        untuk menggagalkan permintaan, dan bukan alasan untuk menaikkan rute
        menjadi bisa menulis.
        """
        if self.env.cr.readonly:
            return
        company = company or self.env.company
        if not company:
            return
        try:
            config = self._read_config(company)
            if config:
                config.sudo().write(values)
        except Exception:  # noqa: BLE001 - pencatatan tidak boleh memblokir
            _logger.warning("Presenly SaaS: could not record %s", values, exc_info=True)

    # ------------------------------------------------------------------
    # What the blocked page needs
    # ------------------------------------------------------------------
    @api.model
    def blocked_page_values(self, error=None, message=None):
        """Nilai halaman blokir. Tanpa satu pun rahasia."""
        company = self.env.company
        config = self._read_config(company)
        subscription = self.env['presenly.saas.subscription'].sudo().search(
            [('company_id', '=', company.id)], limit=1
        )
        reason = self.block_reason(company)
        return self._blocked_values(
            reason, error, message=message,
            company=company, config=config, subscription=subscription,
        )

    @api.model
    def _blocked_values(self, reason, error=False, message=None, company=None,
                        config=None, subscription=None):
        """Nilai halaman blokir, dari record yang sudah dibaca pemanggilnya."""
        company = company or self.env.company
        config = config if config is not None else self._read_config(company)
        if subscription is None:
            subscription = self.env['presenly.saas.subscription'].sudo().search(
                [('company_id', '=', company.id)], limit=1
            )

        def when(value):
            """Cap waktu dalam zona waktu pembacanya, atau False.

            Zona waktu dibaca dari pengguna, bukan dari server: yang membaca
            halaman ini sedang menilai kapan terakhir kali sistemnya sendiri
            menjawab.
            """
            return format_datetime(self.env, value, tz=self.env.user.tz or 'UTC') if value else False

        return {
            'reason': reason,
            'reason_label': self.reason_label(reason),
            'company_name': company.display_name,
            'status_label': subscription._status_label() if subscription else False,
            'tenant_code': subscription.tenant_code if subscription else False,
            'last_sync_at': when(subscription.last_sync_at) if subscription else False,
            'blocked_since': when(config.blocked_since) if config else False,
            'grace_days': config.grace_days if config else 0,
            'contact_email': subscription.tenant_email if subscription else False,
            'contact_whatsapp': subscription.tenant_whatsapp if subscription else False,
            'is_manager': self.env.user.has_group(
                'presenly_saas.group_presenly_saas_manager'
            ),
            'error': error,
            'message': message,
            'base_url': config.base_url if config else False,
            'tenant_code_setting': config.tenant_code if config else False,
            'api_key_set': bool(config.api_key) if config else False,
        }

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------
    @api.model
    def is_allowed(self, operation=None):
        """Return True when ``operation`` may proceed.

        ``operation`` is only used for logging and for the error message. The
        decision itself is per company, not per operation.
        """
        if self.env.context.get(SKIP_CONTEXT_KEY):
            return True
        return self.state()['effective_state'] == 'allowed'

    @api.model
    def check(self, operation=None):
        """Raise a UserError when the subscription blocks ``operation``."""
        if self.is_allowed(operation):
            return True

        state = self.state()
        message = _(
            "Presenly SaaS subscription is not active (status: %(status)s). "
            "Renew the subscription, or ask a Presenly SaaS manager to review "
            "the connection settings.",
            status=state['status'],
        )
        if operation:
            _logger.info("Presenly SaaS guard blocked %s", operation)
        raise UserError(message)

    @api.model
    def has_feature(self, code=None):
        """Apakah paket tenant ini mencakup fitur `code`.

        Aturan yang dipegang sama dengan sisi SaaS, dan sengaja konservatif:

        - Tanpa kode, atau tanpa snapshot, atau snapshot tanpa daftar fitur:
          **True**. Tidak ada data bukan alasan untuk mencabut akses. Ini juga
          yang membuat instalasi lama tetap berjalan, karena field `plan_features`
          baru terisi setelah penyegaran pertama.
        - Paket yang tidak terdaftar di sisi SaaS juga dikirim dengan seluruh
          fitur terbuka, jadi tidak ada kejadian "paket salah tulis lalu akses
          hilang" tanpa keputusan eksplisit seseorang.

        Karena itu, `False` hanya keluar bila server benar-benar mengirim
        `included: false` untuk kode tersebut.
        """
        if not code:
            return True

        subscription = self._subscription_snapshot()
        if not subscription or not subscription.plan_features:
            return True

        # Hanya `included: false` yang eksplisit yang mencabut akses. Kode yang
        # tidak disebut server dapat berarti katalog di sisi SaaS lebih tua
        # daripada modul ini, dan itu bukan alasan untuk memblokir.
        return code not in subscription._missing_feature_codes()

    @api.model
    def missing_features(self):
        """Kode fitur yang tidak termasuk pada paket tenant ini."""
        subscription = self._subscription_snapshot()
        if not subscription:
            return []
        return sorted(subscription._missing_feature_codes())
