# Plan Final Implementasi `presenly_saas`

**Addon:** `custom_addons/presenly_saas`
**Nama:** Presenly SaaS
**Platform:** Odoo 19.0
**Depends:** `base`, `web`
**Versi dokumen:** FINAL v4
**Status:** F0-F6 SELESAI. Endpoint di `backend_presenly` sudah ada.
Lihat §16 untuk catatan as-built dan bukti verifikasi.

Addon **standalone** yang menghubungkan instalasi Odoo ini dengan control plane
SaaS Presenly (`backend_presenly`): identitas tenant, kredensial, status
langganan, seat usage, dan banner peringatan backend.

Kebijakan produk: **full access**. Tidak ada gating fitur per paket. Selama
langganan sah, semua fitur tersedia.

---

## 0. Ringkasan

| Aspek                      | Keputusan                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------- |
| Bentuk                     | Addon baru berdiri sendiri, punya menu root sendiri                                         |
| `depends`                  | `base`, `web`                                                                               |
| Mengubah `presenly` lama   | **Nol file**                                                                                |
| Mewarisi model/view native | **Nol**: tidak ada `_inherit` ke model bisnis native, tidak ada `inherit_id` ke view native |
| Halaman Settings           | **Milik sendiri** (`Presenly SaaS → Configuration`), bukan menumpang Settings native Odoo   |
| Arah data                  | Pull dari SaaS (read-only). SaaS = source of truth                                          |
| Gating fitur               | **Tidak ada**: kebijakan full access (§6)                                                   |
| Penegakan                  | Policy dial (`off`/`warn`/`enforce`) + API guard. Tidak ada addon jembatan                  |
| Banner                     | Dikerjakan di seluruh backend                                                               |
| Bahasa                     | String sumber Inggris + `i18n/id.po` Indonesia                                              |
| antislop                   | **DURING**                                                                                  |
| Prasyarat                  | 1 endpoint baru di `backend_presenly` (§2)                                                  |

---

## 1. Batasan arsitektur

### 1.1 Tanpa mengubah `presenly` lama

Tidak ada file di `custom_addons/presenly` yang disentuh. Tidak ada `_inherit`
terhadap `presenly.permission`, `presenly.overtime.request`,
`presenly.approval.rule`, `presenly.work.location.schedule`, atau
`presenly.setup.guide`.

### 1.2 Tanpa modul native Odoo

Tidak memakai dependensi bisnis native: `hr`, `hr_attendance`, `hr_holidays`,
`hr_homeworking`, `mail`, `base_setup`. Konsekuensinya:

- Tidak ada `_inherit` ke `hr.attendance`, `hr.employee`, `hr.leave`,
  `res.config.settings`, atau model bisnis native lain.
- Tidak ada `inherit_id` ke `base.res_config_settings_view_form` atau view
  native lain. Halaman pengaturan dibuat sendiri sebagai form penuh.
- Tidak ada penegakan otomatis di titik check-in / pengajuan izin / cuti /
  lembur.
- Tidak memakai `ir.config_parameter` sebagai penyimpanan. Semua nilai
  disimpan di kolom model milik addon ini.

### 1.2b Pembalikan batasan: Settings native dipakai

Batasan awal "tidak menggunakan modul native dari Odoo" **dibatalkan atas
permintaan produk**, khusus untuk satu hal: konfigurasi koneksi kini berada di
blok Presenly SaaS pada halaman Settings native, lewat inherit
`base.res_config_settings_view_form`.

Yang tetap berlaku:

- Tidak mengubah addon `presenly`.
- Tidak mewarisi model bisnis native (`hr.attendance`, `hr.employee`, dan
  sejenisnya). Yang di-inherit hanya `res.config.settings`, yaitu model
  pengaturan, bukan model bisnis.
- Penyimpanan nilai tetap di `presenly.saas.config`; tidak ada data yang
  dipindah ke `ir.config_parameter`, dan tidak ada duplikasi.

Form koneksi milik modul sendiri kini hanya-baca dan tidak punya menu, sehingga
hanya ada satu tempat mengubah konfigurasi.

### 1.3 Batas yang tidak bisa dihindari

| Dipakai                              | Alasan                              |
| ------------------------------------ | ----------------------------------- |
| `base`                               | setiap addon Odoo                   |
| `web`                                | banner backend (§7.4)               |
| `models.Model` / `AbstractModel`     | ORM                                 |
| `ir.cron` (via `ir_cron_data.xml`)   | penjadwalan refresh                 |
| `res.company` (Many2one saja)        | pemisahan konfigurasi multi-company |
| `res.groups` / `ir.model.access`     | hak akses                           |
| `ir.actions.act_window` / `menuitem` | navigasi                            |

Tidak ada lagi yang diambil dari sisi native.

---

## 2. Prasyarat di `backend_presenly`

`/api/subscriptions/status` yang ada dijaga `authMiddleware` (JWT user), jadi
tidak bisa dipakai server-to-server. Wajib ditambah di
`src/routes/externalRoutes.js`, mengikuti pola guard yang sudah ada
(`apiKeyAuth` + `externalLimiter` + `requireExternalTenant`):

```js
router.get(
  "/v1/subscription",
  apiKeyAuth,
  externalLimiter,
  requireExternalTenant,
  externalSubscriptionController.getSubscription,
);
```

File baru:

| File                                                | Isi                                                                                                           |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `src/controllers/externalSubscriptionController.js` | handler + audit ke `ExternalSyncLog` (`entity_type = 'subscription'`)                                         |
| `src/services/ExternalSubscriptionService.js`       | `resolveTenantClient()`, `ClientSubscription`, `resolveSubscription()`, `PricingSetting`, hitung `seats_used` |

### 2.1 Kontrak respons

```json
{
  "success": true,
  "data": {
    "tenant_code": "pelni",
    "client_name": "PT Pelayaran Nusantara",
    "plan_type": "premium",
    "status": "active",
    "is_trial": false,
    "trial_ends_at": null,
    "current_period_end": "2026-10-01T00:00:00.000Z",
    "days_remaining": 12,
    "seat_limit": 50,
    "seats_used": 42,
    "price_per_user": 30000,
    "schema_version": "1.0.0",
    "server_time": "2026-09-18T10:05:00.000Z"
  }
}
```

Tidak ada field `features`: kebijakan full access.

Error memakai konvensi yang sudah ada: `TENANT_REQUIRED`, `TENANT_NOT_FOUND`,
`RATE_LIMITED`, 401 untuk API key salah. Dokumentasi + contoh `curl`
ditambahkan di `backend_presenly/docs/`.

---

## 3. Struktur addon

```
custom_addons/presenly_saas/
├── __init__.py
├── __manifest__.py
├── PLAN.md                              # dokumen ini
├── README.md
├── data/
│   ├── presenly_saas_data.xml
│   └── ir_cron_data.xml                 # refresh berkala
├── models/
│   ├── __init__.py
│   ├── presenly_saas_config.py          # pengaturan koneksi (halaman sendiri)
│   ├── presenly_saas_subscription.py    # cache status langganan
│   ├── presenly_saas_sync_log.py        # audit tarikan
│   └── presenly_saas_guard.py           # AbstractModel: API guard + policy
├── services/
│   ├── __init__.py
│   └── saas_client.py                   # klien HTTP
├── security/
│   ├── presenly_saas_security.xml
│   └── ir.model.access.csv
├── static/
│   ├── description/
│   │   └── icon.png                     # SUDAH DIBUAT (256x256, logo Presenly)
│   └── src/banner/                      # OWL banner untuk web.assets_backend
│       ├── presenly_saas_banner.js
│       ├── presenly_saas_banner.xml
│       └── presenly_saas_banner.scss
├── views/
│   ├── presenly_saas_config_views.xml
│   ├── presenly_saas_subscription_views.xml
│   ├── presenly_saas_sync_log_views.xml
│   └── presenly_saas_menus.xml
├── tests/
│   ├── __init__.py
│   ├── test_saas_client.py
│   ├── test_config.py
│   └── test_guard_contract.py
└── i18n/
    ├── id.po                            # terjemahan Indonesia (lengkap)
    └── en.po                            # override istilah Inggris (opsional)
```

### 3.1 `__manifest__.py`

```python
{
    'name': 'Presenly SaaS',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Langganan Presenly SaaS untuk instalasi Odoo ini',
    'author': 'Presenly',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/presenly_saas_security.xml',
        'security/ir.model.access.csv',
        'data/presenly_saas_data.xml',
        'data/ir_cron_data.xml',
        'views/presenly_saas_config_views.xml',
        'views/presenly_saas_subscription_views.xml',
        'views/presenly_saas_sync_log_views.xml',
        'views/presenly_saas_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'presenly_saas/static/src/banner/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
```

### 3.2 Logo: SELESAI

`static/description/icon.png` sudah dibuat: 256×256, RGBA transparan, sumber
`Presenly/web_presenly/public/assets/presenly.webp` (512×488), di-resize LANCZOS
lalu di-pad ke kanvas persegi. Dipakai sebagai `web_icon` pada menu root.

---

## 4. Model

### 4.1 `presenly.saas.config`: pengaturan koneksi

Model nyata (bukan `res.config.settings`, bukan `ir.config_parameter`). Pola
single-record per company via `_get_or_create()`.

| Field                | Tipe                     | Default         | Catatan                                              |
| -------------------- | ------------------------ | --------------- | ---------------------------------------------------- |
| `name`               | Char                     | `Presenly SaaS` |                                                      |
| `company_id`         | Many2one `res.company`   | `env.company`   | multi-company                                        |
| `active`             | Boolean                  | True            |                                                      |
| `enabled`            | Boolean                  | False           | master switch; tidak ada panggilan keluar bila False |
| `environment`        | Selection                | `production`    | `production` / `sandbox`                             |
| `base_url`           | Char                     | :               | origin saja, tanpa `/api`                            |
| `tenant_code`        | Char                     | :               | dikirim sebagai `X-Tenant-ID`                        |
| `api_key`            | Char (`password="True"`) | :               | dikirim sebagai `X-API-Key`                          |
| `timeout_seconds`    | Integer                  | 10              |                                                      |
| `retry_count`        | Integer                  | 2               |                                                      |
| `guard_mode`         | Selection                | **`warn`**      | `off` / `warn` / `enforce` (§6)                      |
| `grace_days`         | Integer                  | 7               | toleransi saat SaaS tak terjangkau                   |
| `show_banner`        | Boolean                  | True            | tampilkan banner backend saat status negatif         |
| `last_check_at`      | Datetime                 | :               | readonly                                             |
| `last_check_status`  | Selection                | :               | `success` / `failed`                                 |
| `last_check_message` | Text                     | :               | pesan hasil Test Connection, tanpa kredensial        |

Constraint: satu record per `company_id`.

Method:

- `action_test_connection()` → panggil `GET /v1/subscription`, tulis
  `last_check_*`, `UserError` bila gagal.
- `action_refresh_subscription()` → panggil endpoint yang sama, tulis ke
  `presenly.saas.subscription` + `presenly.saas.sync.log`.

### 4.2 `presenly.saas.subscription`: cache langganan

| Field                                     | Tipe                                                               |
| ----------------------------------------- | ------------------------------------------------------------------ |
| `company_id`                              | Many2one `res.company`                                             |
| `config_id`                               | Many2one `presenly.saas.config`                                    |
| `tenant_code`, `client_name`, `plan_type` | Char                                                               |
| `status`                                  | Selection `trial` / `active` / `expired` / `suspended` / `unknown` |
| `is_trial`                                | Boolean                                                            |
| `trial_ends_at`, `current_period_end`     | Datetime                                                           |
| `days_remaining`                          | Integer (computed)                                                 |
| `seat_limit`, `seats_used`                | Integer                                                            |
| `seat_usage_percent`                      | Float (computed)                                                   |
| `price_per_user`                          | Integer                                                            |
| `schema_version`                          | Char                                                               |
| `server_time`                             | Datetime                                                           |
| `last_sync_at`                            | Datetime                                                           |
| `state_source`                            | Selection `live` / `cached` / `unreachable`                        |
| `grace_until`                             | Datetime (computed: `last_sync_at + grace_days`)                   |

Constraint: satu record per `company_id`. Method `_effective_state()`
mengembalikan `allowed` / `blocked` / `unknown` menurut `guard_mode` +
`grace_until`.

### 4.3 `presenly.saas.sync.log`

`create_date`, `company_id`, `endpoint`, `http_status`, `duration_ms`,
`success`, `error_message`. **Tidak menyimpan** API key, header, atau body
mentah. Retensi: dipangkas > 90 hari oleh cron yang sama.

---

## 5. Klien HTTP: `services/saas_client.py`

Kelas `PresenlySaasClient(config)`:

- Header: `X-API-Key`, `X-Tenant-ID`, `Accept: application/json`.
- `verify=True` selalu, tanpa opsi mematikan TLS.
- Retry dengan backoff hanya untuk error jaringan dan 5xx. Tidak retry 400/401.
- `SaasClientError(code, http_status, message)`; pesan error tidak pernah
  memuat API key.
- Logging `_logger.info` berisi URL, status, durasi; nilai header diredaksi.
- Validasi `schema_version`; versi tak dikenal → tolak, cache lama dipertahankan.
- `requests` sudah tersedia di `requirements.txt` (2.31.0 untuk Python ≥ 3.11).

---

## 6. Kebijakan full access & policy dial

### 6.1 Tidak ada gating fitur

Kebijakan produk: **full access**. Konsekuensinya:

- Tidak ada model master fitur, tidak ada relasi `feature_ids`, tidak ada
  tabel `plan_features` di sisi SaaS, tidak ada field `features` di respons.
- Tidak ada menu **Features**.
- `has_feature(code)` tetap disediakan di API guard sebagai _shim_ yang selalu
  mengembalikan `True`, agar modul konsumen (sekarang atau nanti) punya
  kontrak yang stabil dan tidak perlu diubah bila gating ditambahkan di masa
  depan. Perilakunya didokumentasikan tegas di README dan docstring.

### 6.2 Apa itu `guard_mode`

Dial kebijakan: menentukan seberapa jauh addon bereaksi saat status langganan
negatif (`trial` lewat, `expired`, `suspended`):

| Nilai     | Efek yang benar-benar terjadi di addon ini                                              |
| --------- | --------------------------------------------------------------------------------------- |
| `off`     | Status hanya terlihat di dashboard. Tidak ada banner. Tidak ada blokir.                 |
| `warn`    | Dashboard + **banner peringatan** di backend. Tidak ada blokir.                         |
| `enforce` | Sama seperti `warn`, PLUS `guard.check()` menaikkan `UserError` untuk **pemanggilnya**. |

Default **`warn`** karena aman: masalah kelihatan, tapi status basi atau salah
konfigurasi tidak bisa mengunci orang keluar dari sistem.

### 6.3 Kenyataan penting soal `enforce`

Karena addon ini tidak menyentuh model bisnis native, `enforce` **tidak
memblokir apa pun dengan sendirinya**. Ia hanya membuat API guard menjawab
"diblokir". Yang menghentikan operasi adalah **modul yang memanggil** API itu.

Di plan ini tidak ada modul jembatan. Jadi:

- `off` dan `warn` → berfungsi penuh sekarang.
- `enforce` → tersimpan sebagai kebijakan + API siap pakai, belum ada konsumen.

### 6.4 API yang disediakan (`presenly.saas.guard`, AbstractModel)

```python
env['presenly.saas.guard'].check('attendance.check_in')      # raise UserError bila diblokir
env['presenly.saas.guard'].is_allowed('overtime.create')     # -> bool
env['presenly.saas.guard'].has_feature('apa pun')            # -> True (full access)
env['presenly.saas.guard'].state()                           # -> dict lengkap
env['presenly.saas.guard'].banner_payload()                  # -> dict untuk banner
```

Bila `enabled = False`, semua mengembalikan lolos. Context key
`presenly_saas_skip_guard=True` disepakati sebagai cara operasi sistem
(import, migrasi, cron internal) melewati guard.

---

## 7. Views, menu, banner

### 7.1 Halaman Configuration (form penuh milik sendiri)

Form `presenly.saas.config` dengan tab:

- **Connection**: `enabled`, `environment`, `base_url`, `tenant_code`,
  `api_key`, `timeout_seconds`, `retry_count`
- **Policy**: `guard_mode`, `grace_days`, `show_banner`
- **Diagnostics**: panel readonly `last_check_*` + tombol **Test Connection**
  dan **Refresh Subscription** (`type="object"`)

Tidak menumpang `base.res_config_settings_view_form` sama sekali.

### 7.2 Menu

Menu root sendiri, `web_icon` = logo Presenly:

```
Presenly SaaS                       (root, web_icon static/description/icon.png)
├── Subscription                    → action: form presenly.saas.subscription
├── Sync Log                        → action: list presenly.saas.sync.log
└── Configuration
    └── Presenly SaaS Connection    → action: form presenly.saas.config
```

### 7.3 Dashboard Subscription

Form `presenly.saas.subscription` readonly: badge `status`, plan, tenant,
tanggal berakhir, `days_remaining`, `progressbar` `seat_usage_percent`,
`state_source`, tombol **Refresh Now**.

### 7.4 Banner backend

Komponen OWL di `static/src/banner/`, terdaftar di `web.assets_backend`.

- Muncul hanya bila `show_banner = True` AND `enabled = True` AND
  `guard_mode != 'off'`.
- Warna menurut tingkat: kuning untuk `state_source='cached'` / trial hampir
  habis, merah untuk `expired` / `suspended`.
- Isi: `plan_type`, `status`, sisa hari, tombol menuju halaman Configuration.
- Dapat ditutup per sesi (`sessionStorage`), tidak mengganggu chrome `web`
  native selain menyisipkan satu elemen.
- Sumber data dari `presenly.saas.guard.banner_payload()` via
  `/web/dataset/call_kw`, dipanggil sekali saat boot. Tanpa polling.

---

## 8. Security

- Group `group_presenly_saas_user` (read) dan `group_presenly_saas_manager`
  (read + write config), kategori `base.module_category_productivity`.
- `ir.model.access.csv`: `presenly.saas.config`: write hanya manager;
  `presenly.saas.subscription` dan `presenly.saas.sync.log`: read untuk user,
  write hanya server (`sudo()`).
- Record rule multi-company pada `company_id`.
- `group_presenly_saas_user` di-`implied` oleh `base.group_user` agar banner
  bisa membaca payload status tanpa penugasan manual.
- Field `api_key` memakai widget password; nilainya diredaksi di semua log.
- `presenly.saas.sync.log` tidak menyimpan body respons.

---

## 9. Cron

`data/ir_cron_data.xml`:

| Cron                                | Interval | Isi                                                                          |
| ----------------------------------- | -------- | ---------------------------------------------------------------------------- |
| Presenly SaaS: Refresh Subscription | 1 hari   | loop config `enabled=True`; refresh; tulis sync log; bersihkan log > 90 hari |

Aturan keras: kegagalan tarik **tidak** mengubah `status` menjadi `expired`.
Status negatif hanya diambil dari respons SaaS yang benar-benar diterima.

---

## 10. Error handling & grace

| Kejadian                                   | Perilaku                                                              |
| ------------------------------------------ | --------------------------------------------------------------------- |
| `enabled=False` atau kredensial kosong     | tidak ada panggilan keluar; guard meloloskan                          |
| 401 API key salah                          | `last_check_status='failed'`, pesan jelas, **tidak** retry            |
| 400 `TENANT_REQUIRED` / `TENANT_NOT_FOUND` | idem, pesan spesifik                                                  |
| 429 `RATE_LIMITED`                         | backoff, retry sekali                                                 |
| Timeout / koneksi gagal                    | retry, lalu `state_source='unreachable'`, pakai cache + `grace_until` |
| JSON tidak sesuai skema                    | tolak, pertahankan cache lama, catat di sync log                      |

---

## 11. Bahasa (i18n)

- Semua string sumber ditulis dalam **Inggris** (konvensi Odoo).
- `i18n/id.po` memuat terjemahan Indonesia **lengkap**: 132 entri, diekspor
  langsung dari `.pot` sehingga msgid-nya persis.
- `i18n/en.po` **tidak dibuat**: string sumbernya sudah bahasa Inggris, jadi
  tidak ada override yang dibutuhkan.
- Pengguna memilih bahasa via Preferences Odoo. Tidak ada penampilan dua bahasa
  sekaligus dalam satu label, itu bukan pola Odoo dan merusak tata letak form.

---

## 12. Fase implementasi

| Fase   | Isi                                                                              | Estimasi   |
| ------ | -------------------------------------------------------------------------------- | ---------- |
| **F0** | Endpoint `/api/external/v1/subscription` + docs + tes di `backend_presenly`      | 0.5–1 hari |
| **F1** | Skeleton addon: manifest, security, model config, views sendiri, menu root, ikon | 1 hari     |
| **F2** | `saas_client.py` + `action_test_connection` + `action_refresh_subscription`      | 1 hari     |
| **F3** | `presenly.saas.subscription` + `sync.log` + cron                                 | 0.5–1 hari |
| **F4** | `presenly.saas.guard` + README kontrak integrasi                                 | 0.5 hari   |
| **F5** | Dashboard polish + banner OWL                                                    | 1 hari     |
| **F6** | Tes, README, `id.po` + `en.po`, hardening                                        | 1 hari     |

Total ±5.5–6.5 hari kerja. F0 dikerjakan di repo `backend_presenly` dan bisa
paralel dengan F1.

---

## 13. Acceptance criteria

1. `-i presenly_saas` berhasil di DB yang hanya punya `base` + `web`
   (tanpa `presenly`, `hr`, `hr_attendance`, `hr_holidays`, `mail`).
2. Tidak ada file di `custom_addons/presenly` yang berubah (`git status`).
3. Tidak ada `inherit_id` ke view native dan tidak ada `_inherit` ke model
   bisnis native di seluruh isi addon.
4. Tidak ada model/tabel fitur dan tidak ada field `features` di mana pun.
5. Menu **Presenly SaaS** tampil dengan logo Presenly, berisi 3 entri (§7.2).
6. Configuration menyimpan base URL, tenant code, API key; API key selalu
   masked.
7. **Test Connection** menampilkan plan, status, tanggal berakhir, dan seat
   terpakai/limit, atau pesan error spesifik.
8. Cron harian memperbarui `presenly.saas.subscription` dan menulis
   `presenly.saas.sync.log`.
9. Banner muncul saat `show_banner=True` + `guard_mode != 'off'` + status
   negatif, warna sesuai tingkat, bisa ditutup, dan hilang saat `enabled=False`.
10. `guard_mode='off'` → tidak ada banner. `'warn'` → banner ada. `'enforce'` →
    `guard.check()` menaikkan `UserError` bagi pemanggil.
11. SaaS tidak dapat dihubungi + masih `grace_days`: tidak ada blokir,
    `state_source='cached'`, banner kuning.
12. `has_feature()` mengembalikan `True` untuk kode apa pun saat `enabled=True`.
13. Ganti bahasa user ke Indonesia → seluruh label form, menu, pesan error,
    dan teks banner berbahasa Indonesia.
14. Seluruh tes hijau: `odoo-bin -d <db> -i presenly_saas --test-enable`.

---

## 14. Risiko & mitigasi

| Risiko                                                  | Mitigasi                                                                  |
| ------------------------------------------------------- | ------------------------------------------------------------------------- |
| `enforce` tidak memblokir apa pun tanpa modul pemanggil | didokumentasikan terbuka di README + §6.3; default `warn`                 |
| Server Odoo tidak punya akses internet keluar           | allowlist domain SaaS; grace; default `warn`                              |
| SaaS down saat jam absen                                | tidak pernah blokir karena error jaringan                                 |
| API key bocor lewat log                                 | redaksi wajib, field masked, tidak disimpan di sync log                   |
| `EXTERNAL_API_KEY` masih satu key global                | **Sudah ditangani**: kunci per tenant di `external_api_keys`; tenant otoritatif dari kunci, dan 403 bila `X-Tenant-ID` tidak cocok. Key global dipertahankan sebagai legacy |
| Banner mengganggu chrome backend                        | komponen terisolasi, bisa ditutup, dimatikan lewat `show_banner`          |
| Perubahan bentuk respons SaaS                           | `schema_version` divalidasi                                               |

---

## 15. Riwayat keputusan

| #   | Pertanyaan                       | Keputusan                                                                                           |
| --- | -------------------------------- | --------------------------------------------------------------------------------------------------- |
| 1   | Ikon                             | Dikonversi dari `presenly.webp` → `static/description/icon.png` (256×256, transparan). **Selesai.** |
| 2   | Banner backend                   | Dikerjakan (§7.4). Konsekuensi: `depends` mencakup `web`.                                           |
| 3   | Mode default                     | `warn` (§6.2).                                                                                      |
| 4   | Addon jembatan / penegakan nyata | Tidak ada. Lingkup berhenti di policy + API guard (§6.3).                                           |
| 5   | Entitlement fitur                | **Full access.** Model fitur, relasi, field respons, dan menu Features dibuang seluruhnya (§6.1).   |
| 6   | Bahasa                           | Dua-duanya: string sumber Inggris + `i18n/id.po` lengkap (§11).                                     |
| 7   | antislop                         | **DURING**: dipakai sebagai panduan selama pengerjaan UI.                                           |

---

## 16. Catatan as-built

### 16.1 Yang sudah dikerjakan

F0 dan F1 sampai F6 selesai.

F0 (repo `Presenly/backend_presenly`):

| Berkas                                              | Isi                                                                                                                                                  |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/routes/externalRoutes.js`                      | route `GET /v1/subscription` ditambah di baris 2 block integrasi eksternal                                                                           |
| `src/services/ExternalSubscriptionService.js`       | ambil langganan dari tabel master, `seats_used` dari DB tenant, koreksi status lewat `resolveSubscription()`, `seat_limit` null untuk paket berbayar |
| `src/controllers/externalSubscriptionController.js` | handler + audit ke `external_sync_logs` (metadata saja, tanpa isi langganan)                                                                         |
| `tests/test_external_subscription.test.js`          | 16 kasus unit service + controller                                                                                                                   |
| `tests/test_external_subscription_routes.test.js`   | 8 kasus HTTP nyata (401 tanpa key, 200 dengan key, galat terstruktur, audit, route lain tidak tertimpa)                                              |
| `docs/external-subscription.md`                     | kontrak lengkap                                                                                                                                      |
| `src/routes/index.js`                               | komentar mount `/api/external` diperbarui                                                                                                            |

Dua keputusan implementasi di sisi SaaS yang melampaui rencana:

1. **Resolusi klien ketat.** `resolveClientStrict()` menolak dengan
   `TENANT_NOT_FOUND` bila `clients.tenant_code` tidak cocok, alih-alih
   memakai fallback `resolveTenantClient()` yang mengambil klien pertama.
   Salah tenant untuk data langganan lebih berbahaya daripada gagal jelas.
2. **`seat_limit` null = tidak dibatasi.** Skema `client_subscriptions` tidak
   punya kolom batas kursi untuk paket berbayar, jadi endpoint mengirim `null`
   dan sisi Odoo menyimpannya sebagai `0` (tanpa batas).

Catatan lain: suite Jest repo ini sudah punya 13 suite gagal sebelum F0
(dibuktikan dengan `git stash` pada `externalRoutes.js`), tidak terkait dengan
perubahan ini.

### 16.2 Dua koreksi terhadap rencana

**1. Kegagalan remote dikembalikan sebagai nilai, bukan exception.**
Rencana semula menulis diagnostik lalu `raise UserError`. Itu keliru: exception
yang sampai ke layer RPC membuat Odoo me-rollback seluruh transaksi, sehingga
`last_check_status`, `state_source`, dan baris sync log ikut hilang. Sekarang
`_fetch_and_store` mengembalikan `(subscription, error)` dan aksi memunculkan
notifikasi `danger`. Diagnostik jadi bertahan, dan pengguna tetap melihat sebab
kegagalan.

**2. SCSS banner tidak memakai `min()`.**
`width: min(46rem, calc(100vw - 1.5rem))` membuat compiler Sass Odoo gagal
(`"calc(100vw - 1.5rem)" is not a number for 'min'`), dan kegagalan itu
merusak **seluruh** bundle `web.assets_web`, bukan hanya berkas ini. Diganti
menjadi `width: 46rem; max-width: calc(100vw - 1.5rem)`.

### 16.3 Bukti verifikasi

| Uji                                                                                                    | Hasil                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-i presenly_saas --test-enable --test-tags=/presenly_saas`                                            | **0 failed, 0 error(s) of 48 tests**                                                                                                                                      |
| Modul terpasang di DB tanpa `hr`, `hr_attendance`, `hr_holidays`, `hr_homeworking`, `mail`, `presenly` | Lolos. Terpasang hanya `base`, `web`, dan infrastruktur bawaan (`bus`, `html_editor`, `iap`, `base_setup` lewat rantai Odoo sendiri)                                      |
| `git status` pada `custom_addons/presenly` dan `presenly_payroll`                                      | 0 berkas berubah                                                                                                                                                          |
| Bundle `web.assets_web.min.css`                                                                        | Kompilasi bersih, 852 KB, memuat seluruh aturan `.presenly-saas-banner` termasuk media query                                                                              |
| Bundle `web.assets_web.min.js`                                                                         | Memuat komponen banner, template, RPC `get_banner_payload`, dan xmlid server action                                                                                       |
| `get_banner_payload` lewat HTTP dengan sesi nyata                                                      | `{visible: true, severity: danger, status: expired, is_manager: true}`, tanpa rahasia                                                                                     |
| Cron saat startup dengan host SaaS tidak dapat dijangkau                                               | Menulis sync log `success: false`, `http_status: 0`, `duration_ms: 2000` (2 percobaan ulang). Status langganan **tetap `expired`**, hanya `state_source` menjadi `cached` |
| Impor `i18n/id.po` lalu ganti bahasa ke `id_ID`                                                        | Label field, label selection, teks view, dan nama menu berbahasa Indonesia                                                                                                |

### 16.4 Batas yang tetap berlaku

`Mode Penegakan = Wajibkan` tidak memblokir apa pun tanpa modul yang memanggil
`presenly.saas.guard`. Ini bukan kekurangan implementasi, melainkan konsekuensi
dari batasan "tanpa modul native" yang dipilih, dan sudah didokumentasikan di
README §6.
