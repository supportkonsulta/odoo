# Presenly SaaS (`presenly_saas`)

Addon Odoo 19 yang menghubungkan instalasi Odoo ini dengan control plane SaaS
Presenly: identitas tenant, kredensial, status langganan, pemakaian kursi, dan
banner peringatan di backend.

Modul ini **berdiri sendiri**. Ia tidak mengubah addon `presenly`, tidak
mewarisi model atau view native Odoo, dan tidak menarik dependensi HR.

---

## 1. Persyaratan

| Kebutuhan         | Keterangan                                                     |
| ----------------- | -------------------------------------------------------------- |
| Odoo              | 19.0                                                           |
| Modul             | `base`, `web` (tidak lebih)                                    |
| Akses keluar      | Server Odoo harus bisa mencapai host Presenly SaaS (HTTPS)     |
| **Endpoint SaaS** | `GET /api/external/v1/subscription`, sudah tersedia (lihat §3) |

Kalau host SaaS belum bisa dijangkau, modul tetap terpasang dan bisa
dikonfigurasi; hanya tombol **Uji Koneksi** dan **Segarkan Langganan** yang
akan melaporkan gagal, tanpa merusak status langganan yang tersimpan.

---

## 2. Instalasi

```bash
odoo-bin -d <db> -i presenly_saas
```

Setelah terpasang ada dua permukaan, dan keduanya tidak tumpang tindih:

```
Settings (native Odoo)
└── Presenly SaaS        <- SATU-SATUNYA tempat mengubah konfigurasi

Presenly SaaS (menu aplikasi)
├── Subscription         status, profil perusahaan, paket & fitur
├── Data Presensi        cermin log presensi dari server SaaS
├── Rekap Presensi       cermin rekap bulanan per pegawai
├── Fitur Presenly       katalog endpoint yang disediakan server
├── Sync Log             jejak setiap panggilan ke server SaaS
└── Configuration
    └── Settings         pintasan ke blok di Settings native
```

Menu aplikasi hanya berisi hal operasional. Konfigurasi koneksi berada di
halaman Settings native, bukan di form kedua, supaya tidak ada dua layar yang
mengedit data yang sama.

Keduanya hanya terlihat oleh group **Presenly SaaS / Manajer**. Pengguna
internal lain tetap menerima banner langganan, yang memang satu-satunya hal
yang mereka butuhkan.

> **Prasyarat hak akses.** Menyetel integrasi butuh dua hal sekaligus: hak
> membuka halaman Settings native Odoo (`Settings`, yaitu `base.group_system`),
> **dan** group **Presenly SaaS / Manajer** untuk melihat serta mengubah blok
> dan kunci API-nya. Group Manajer sendiri tidak memberi hak membuka Settings,
> dan sebaliknya administrator Odoo tanpa group itu tidak melihat blok ini
> sama sekali. Praktisnya: administrator Odoo.

---

## 3. Endpoint di sisi SaaS

**Sudah diimplementasikan** di repo `Presenly/backend_presenly`:

- Route: `src/routes/externalRoutes.js`
- Controller: `src/controllers/externalSubscriptionController.js`
- Service: `src/services/ExternalSubscriptionService.js`
- Kontrak lengkap: `backend_presenly/docs/external-subscription.md`

Guard-nya sama dengan route eksternal lain: `apiKeyAuth`, `externalLimiter`,
`requireExternalTenant`.

```js
router.get(
  "/v1/subscription",
  apiKeyAuth,
  externalLimiter,
  requireExternalTenant,
  externalSubscriptionController.getSubscription,
);
```

Bentuk responsnya:

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
    "seat_limit": null,
    "seats_used": 42,
    "price_per_user": 30000,
    "schema_version": "1.0.0",
    "server_time": "2026-09-18T10:05:00.000Z"
  }
}
```

Header permintaan: `X-API-Key` dan `X-Tenant-ID` (wajib).

### Kredensial yang dipakai

| Jenis | Cara mendapatkan | Catatan |
|---|---|---|
| **Kunci per tenant** (disarankan) | Web admin: menu **Integrasi Odoo**. Super Admin: tab **Integrasi** pada kelola klien | Hanya berlaku untuk tenant pembuatnya. Bila `X-Tenant-ID` diisi tenant lain, server menolak **403** |
| Key global lama (`EXTERNAL_API_KEY`) | Dari `.env` server SaaS | Warisan. Masih berlaku supaya integrasi yang sudah jalan tidak putus, tetapi satu key bisa membaca **semua** tenant |

Kunci per tenant berbentuk `psk_` diikuti 40 karakter heksadesimal, dan **hanya
ditampilkan sekali** saat dibuat. Yang disimpan di server hanya hash-nya.

Untuk memeriksa sebuah kunci sebelum mengisinya di sini:

```bash
curl -s -H "X-API-Key: <kunci>" -H "X-Tenant-ID: <kode tenant>" \
  https://<host>/api/external/v1/meta/health
```

Balasannya menyebut jenis kunci dan tenant yang dilayaninya. Tombol **Uji
Koneksi** di modul ini tetap memakai `/v1/subscription`, karena jalur guard-nya
sama dan sekaligus mengambil data langganannya.

Nilai `schema_version` divalidasi. Versi yang tidak dikenal ditolak, dan
snapshot lama dipertahankan.

Catatan soal `seat_limit`: nilainya hanya terisi pada masa uji (dari
`trial_user_limit`). Paket berbayar mengirim `null`, yang berarti **tidak
dibatasi**, dan modul ini menyimpannya sebagai `0` supaya baris kursi tidak
ditampilkan. Penjelasan lengkapnya ada di
`backend_presenly/docs/external-subscription.md` §3.1.

### Kebijakan full access

Tidak ada gating fitur per paket. Tidak ada tabel `plan_features`, tidak ada
field `features` di respons, dan tidak ada menu Fitur.
`presenly.saas.guard.has_feature()` selalu mengembalikan `True` supaya modul
konsumen punya kontrak yang stabil bila gating ditambahkan di masa depan.

---

## 4. Konfigurasi

**Settings → Presenly SaaS** (blok di halaman Settings native).

| Blok           | Field                                                                                     |
| -------------- | ----------------------------------------------------------------------------------------- |
| Koneksi        | `Aktifkan Koneksi`, `Base URL`, `Kode Tenant`, `Kunci API`, `Lingkungan`                   |
| Keandalan      | `Batas Waktu`, `Percobaan Ulang`                                                           |
| Kebijakan      | `Mode Penegakan`, `Masa Tenggang`, `Tampilkan Banner`                                      |
| Diagnostik     | hasil pemeriksaan terakhir, tombol **Uji Koneksi**, **Segarkan Langganan**, **Buka Langganan**, **Buka Log Sinkronisasi** |

Odoo menyimpan perubahan settings lebih dulu sebelum menjalankan tombol object
(`SettingsFormController.beforeExecuteActionButton`), jadi nilai yang baru
diketik sudah tersimpan saat tombol bekerja.

### Penyimpanannya di mana

Nilai tetap tersimpan di `presenly.saas.config`, satu record per company, yaitu
model yang sudah dibaca service, guard, cron, dan banner. Field di halaman
Settings hanya jembatan: `compute` membaca record itu dan `inverse` menulisnya
kembali. Jadi tidak ada data yang diduplikasi, dan tidak ada dua sumber
kebenaran.

Konsekuensinya, kunci API **tidak** disimpan di `ir.config_parameter`, sehingga
tetap punya ACL, record rule multi-company, dan pembatasan field per group
sendiri.

Setiap field di halaman Settings punya `inverse` sendiri. Ini penting:
`inverse` bersama yang menulis semua field sekaligus akan berbahaya, karena pada
penyimpanan sebagian field yang tidak dikirim belum dihitung dan masih bernilai
default, sehingga menulisnya akan menimpa `tenant_code` atau kunci API.

Form `presenly.saas.config` sengaja hanya-baca. Ia tidak punya menu, tetapi
tetap ada karena `presenly.saas.subscription.config_id` menunjuk ke sana,
sehingga operator bisa memeriksa asal sebuah snapshot tanpa berpindah layar.

Kegagalan dilaporkan lewat notifikasi, bukan exception. Ini disengaja: exception
yang sampai ke layer RPC akan membuat Odoo me-rollback transaksi, sehingga
diagnostik yang baru saja ditulis ikut hilang.

---

## 4b. Endpoint yang dikonsumsi

| Endpoint | Dipakai untuk | Sifat |
|---|---|---|
| `GET /v1/subscription` | status langganan, profil perusahaan, paket & fitur | tarikan penuh, mengganti snapshot |
| `GET /v1/presenly/features` | katalog fitur eksternal | tarikan penuh, mengganti katalog |
| `GET /v1/presenly/attendance-logs` | Data Presensi | berhalaman, cermin diganti per rentang tanggal |
| `GET /v1/presenly/attendance-recap` | Rekap Presensi | cermin diganti per bulan |

Semua memakai `X-API-Key` + `X-Tenant-ID` yang sama dengan pengaturan koneksi.

### Cermin, bukan arsip

Data presensi dan rekap disimpan sebagai **cermin**: setiap penarikan
mengganti baris pada periode itu, dan periode lain tidak tersentuh. Jadi
tabelnya tidak tumbuh tanpa batas, dan tidak pernah mencampur data basi dengan
data baru.

Penarikan dibatasi 10 halaman per tombol. Kalau batas itu tersentuh, jumlah
yang terambil dibandingkan dengan `meta.total` dari server dan selisihnya
**diberitahukan** ke pengguna, supaya cermin yang terpotong tidak tampak seperti
data yang lengkap.

### Dua arti "fitur" yang sengaja dibedakan

| Istilah | Arti | Asal |
|---|---|---|
| **Fitur Presenly** (menu) | katalog **endpoint** yang disediakan server, status `available` atau `planned` | `GET /v1/presenly/features` |
| **Paket & Fitur** (di Subscription) | **hak paket**: fitur apa yang boleh dipakai tenant menurut `plan_type` | `plan_features` pada respons langganan |

Yang pertama menjawab "apa yang bisa ditarik", yang kedua "apa yang boleh
dipakai". Menggabungkannya akan membuat dua pertanyaan berbeda terlihat sama.

---

## 5. Aturan yang dipegang modul ini

| Aturan                                          | Perilaku                                                                           |
| ----------------------------------------------- | ---------------------------------------------------------------------------------- |
| SaaS adalah sumber kebenaran                    | Status hanya diubah dari respons yang benar-benar diterima                         |
| Kegagalan jaringan tidak pernah memblokir       | Status lama dipertahankan, `Sumber Status` menjadi `Cache` atau `Tidak Terjangkau` |
| Kegagalan jaringan tidak pernah mengubah status | Tidak ada penurunan otomatis ke `Kedaluwarsa`                                      |
| Timeout & 5xx                                   | Diulang sesuai `Percobaan Ulang` dengan backoff                                    |
| 401 dan 400                                     | Tidak diulang, dilaporkan apa adanya                                               |
| Log tidak memuat rahasia                        | Kunci API diredaksi di semua pesan log dan error                                   |

Retensi `Log Sinkronisasi` 90 hari, dipangkas oleh cron yang sama dengan
penyegaran. Aturan yang sama berlaku untuk penarikan presensi: kegagalan
**dikembalikan sebagai nilai**, bukan dilempar sebagai exception, supaya catatan
audit yang baru ditulis tidak ikut ter-rollback.

---

## 6. Mode penegakan

`Mode Penegakan` mengatur seberapa jauh modul bereaksi saat status negatif:

| Nilai             | Yang benar-benar terjadi                                                              |
| ----------------- | ------------------------------------------------------------------------------------- |
| `Nonaktif`        | Status hanya terlihat di halaman Langganan                                            |
| `Peringatan saja` | Halaman Langganan ditambah banner di backend                                          |
| `Wajibkan`        | Banner ditambah `presenly.saas.guard.check()` yang menaikkan galat untuk pemanggilnya |

Default `Peringatan saja`.

**Catatan penting.** Karena modul ini tidak menyentuh model bisnis native,
`Wajibkan` tidak memblokir apa pun dengan sendirinya. Ia hanya membuat API guard
menjawab "diblokir". Yang benar-benar menghentikan sebuah operasi adalah modul
yang memanggil API tersebut.

---

## 7. API guard untuk modul lain

`presenly.saas.guard` adalah `AbstractModel`, dipakai dari Python:

```python
guard = self.env['presenly.saas.guard']

guard.check('attendance.check_in')        # raise UserError bila diblokir
guard.is_allowed('overtime.create')       # -> bool
guard.has_feature('timesheet')            # -> bool, lihat aturan di bawah
guard.missing_features()                  # -> ['audit_log', 'timesheet']
guard.state()                             # -> dict lengkap, termasuk plan_name
                                          #    dan missing_features
```

### Aturan `has_feature()`

Konservatif, dan sengaja sama dengan sisi SaaS:

| Keadaan | Hasil |
|---|---|
| Tanpa kode, tanpa snapshot, atau snapshot tanpa daftar fitur | `True` |
| Kode **tidak disebut** server | `True` |
| Server mengirim `included: false` untuk kode itu | **`False`** |

Baris kedua penting: kode yang tidak disebut bisa berarti katalog di sisi SaaS
lebih tua daripada modul ini. Itu bukan alasan mencabut akses. Hanya
`included: false` yang eksplisit yang menghasilkan `False`.

Label fitur diambil apa adanya dari server SaaS, karena katalognya milik
server. Judul bagian di `Rincian Fitur` diterjemahkan oleh Odoo, labelnya
tidak. Jadi kalau nanti bahasa Indonesia diaktifkan, label fitur tetap sesuai
yang dikirim server.

Perlu dicatat: fitur **tidak** ikut memblokir operasi. `Mode Penegakan =
Wajibkan` menegakkan status langganan, bukan fitur, karena menegakkan fitur
butuh modul pemanggil yang belum ada.

Lewatkan operasi sistem dengan context:

```python
self.env['presenly.saas.guard'].with_context(
    presenly_saas_skip_guard=True
).check('import.attendance')
```

Aturan blokir, secara sengaja konservatif:

- `Koneksi Aktif = False` → selalu lolos.
- `Mode Penegakan != Wajibkan` → selalu lolos.
- `Sumber Status` = `Cache` atau `Tidak Terjangkau` → selalu lolos.
- `Kedaluwarsa` atau `Ditangguhkan`, dari jawaban nyata server → diblokir.
- Masa uji yang sudah lewat tanggalnya → diblokir.
- Belum ada snapshot sama sekali → lolos.

---

## 8. Banner

Komponen OWL yang terdaftar di `main_components`. Muncul hanya bila:

`Koneksi Aktif = True` **dan** `Mode Penegakan != Nonaktif` **dan**
`Tampilkan Banner = True` **dan** status butuh perhatian.

- Warna mengikuti pola `alert` Odoo (`alert-warning` / `alert-danger`), jadi
  kontras dan mode gelap ikut tema tanpa modul ini mendefinisikan palet sendiri.
- Bisa ditutup per sesi; tombol **Buka langganan** hanya muncul untuk Manajer,
  sehingga tidak ada kontrol yang tidak bisa dijalankan.
- Satu panggilan RPC saat boot, tanpa polling. Bila panggilan itu gagal, banner
  hanya tidak muncul dan alasannya dicatat di console.

---

## 9. Pengujian

```bash
odoo-bin -d <db> -i presenly_saas \
  --addons-path=odoo/addons,addons,custom_addons \
  --test-enable --test-tags=/presenly_saas \
  --stop-after-init --no-http
```

110 kasus uji:

| Berkas                         | Cakupan                                                                                                  |
| ------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `tests/test_saas_client.py`    | normalisasi URL, header, retry vs tidak retry, skema, redaksi kunci API                                  |
| `tests/test_config.py`         | singleton per perusahaan, constraint, penyegaran, kegagalan tidak mengubah status, cron, pemangkasan log |
| `tests/test_guard_contract.py` | seluruh matriks mode × status, grace, kontrak full access, payload banner                                |

---

## 10. Bahasa

String sumber ditulis dalam bahasa Inggris. `i18n/id.po` memuat terjemahan
Indonesia lengkap (132 entri). Pengguna memilih bahasa lewat Preferences, dan
keduanya tersedia sekaligus.

Berkas `i18n/en.po` tidak dibuat karena string sumbernya sudah bahasa Inggris,
sehingga tidak ada override yang dibutuhkan.

Regenerasi berkas terjemahan setelah mengubah string:

```bash
# ekspor template
odoo-bin --addons-path=odoo/addons,addons,custom_addons \
  i18n export -c odoo.conf -d <db> -o /tmp/presenly_saas.pot presenly_saas

# muat bahasa lalu impor terjemahan
odoo-bin --addons-path=odoo/addons,addons,custom_addons \
  i18n loadlang -c odoo.conf -d <db> -l id
odoo-bin --addons-path=odoo/addons,addons,custom_addons \
  i18n import -c odoo.conf -d <db> -l id -w custom_addons/presenly_saas/i18n/id.po
```

---

## 11. Struktur

```
presenly_saas/
├── data/           parameter awal, cron
├── i18n/id.po      terjemahan Indonesia
├── models/         config, subscription, sync log, guard, fitur eksternal,
│                   cermin presensi & rekap
├── security/       group, ACL, record rule multi-company
├── services/       klien HTTP (tanpa dependensi Odoo, mudah diuji)
├── static/         ikon + komponen OWL banner
├── tests/          110 kasus uji
├── views/          form, list, search, menu
└── wizard/         pemilih periode penarikan presensi
```

---

## 12. Keputusan desain

| Keputusan                                | Alasan                                                                             |
| ---------------------------------------- | ---------------------------------------------------------------------------------- |
| Konfigurasi di Settings native           | Satu tempat mengubah konfigurasi, dan itu permintaan produk. Sebelumnya modul ini justru menghindari `res.config.settings` |
| Penyimpanan tetap di model sendiri       | Field di Settings hanya jembatan; rahasia tetap punya ACL dan record rule sendiri  |
| `inverse` per field, bukan bersama       | Inverse bersama menulis field yang belum dihitung dan menimpa nilai asli           |
| `has_feature()` dipertahankan            | Kontrak untuk modul konsumen tidak berubah bila gating ditambahkan nanti           |
| Kegagalan sebagai nilai, bukan exception | Agar diagnostik tidak ter-rollback                                                 |
| Warna banner dari token Odoo             | Kontras dan mode gelap mengikuti tema tanpa palet baru                             |
| Satu group saja (`Manajer`)              | Akses baca lewat `base.group_user`; group tambahan tanpa menu hanya menambah beban |
| `i18n/en.po` tidak dibuat                | String sumber sudah bahasa Inggris                                                 |
| Presensi ditarik ke model cermin sendiri | Tidak menyentuh `hr.attendance`; dapat pencarian, filter, dan ekspor bawaan Odoo |
| Cermin diganti per periode               | Tabel tidak tumbuh tanpa batas dan data basi tidak tercampur                       |
| Katalog fitur eksternal dipisah dari hak paket | Dua pertanyaan berbeda: "apa yang bisa ditarik" vs "apa yang boleh dipakai"  |
