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
├── Monitoring Presensi  pivot & grafik dari cermin log
├── Rekap Presensi       cermin rekap bulanan per pegawai
├── Timesheet            daftar, pivot, dan grafik timesheet
├── Pengajuan            cuti, lembur, surat dokter, koreksi presensi,
│                        tukar shift
├── Referensi            lokasi kerja, shift, mode absen, hari libur,
│                        setup hari kerja, proyek
├── Sync Log             jejak setiap panggilan ke server SaaS
│
│   Konfigurasi: Settings → Presenly SaaS (koneksi, keandalan, penarikan
│   terjadwal, kebijakan, diagnostik)
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

Hak paket tidak memblokir apa pun dari sisi ini. `presenly.saas.guard.has_feature()`
tetap dapat dipanggil modul konsumen dengan kontrak yang stabil, dan hasilnya
konservatif: `False` hanya bila server menyatakan `included: false` untuk fitur
itu (aturan lengkapnya di §7).

---

## 4. Konfigurasi

**Settings → Presenly SaaS** (blok di halaman Settings native).

| Blok           | Field                                                                                     |
| -------------- | ----------------------------------------------------------------------------------------- |
| Koneksi        | `Aktifkan Koneksi`, `Base URL`, `Kode Tenant`, `Kunci API`, `Lingkungan`                   |
| Keandalan      | `Batas Waktu`, `Percobaan Ulang`                                                           |
| Penarikan Terjadwal | `Bulan yang Ditarik Cron`, `Penyimpanan (bulan)`                                      |
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
| `GET /v1/presenly/attendance-logs` | Data Presensi | berhalaman, cermin diganti per rentang tanggal |
| `GET /v1/presenly/attendance-recap` | Rekap Presensi | cermin diganti per bulan |
| `GET /v1/work-locations` | Referensi → Lokasi Kerja | cermin diganti seluruhnya |
| `GET /v1/shifts` | Referensi → Shift | idem |
| `GET /v1/attendance-modes` | Referensi → Mode Absen | idem |
| `GET /v1/holidays` | Referensi → Hari Libur | idem |
| `GET /v1/work-day-setups` | Referensi → Setup Hari Kerja | idem |
| `GET /v1/projects` | Referensi → Proyek | idem |
| `GET /v1/leaves` | Pengajuan → Cuti | berhalaman, cermin diganti per bulan |
| `GET /v1/overtimes` | Pengajuan → Lembur | idem |
| `GET /v1/medical-certificates` | Pengajuan → Surat Dokter | idem |
| `GET /v1/attendance-corrections` | Pengajuan → Koreksi Presensi | idem |
| `GET /v1/shift-swaps` | Pengajuan → Tukar Shift | idem |
| `GET /v1/timesheets` | Timesheet | idem |
| `GET /v1/projects` | Referensi → Proyek | cermin diganti seluruhnya |
| `GET /v1/weekly-schedules`, `daily-schedules`, segmen-segmennya | belum dipakai Odoo | tersedia bila dibutuhkan |

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

### Satu arti "fitur"

Kata "fitur" di modul ini hanya berarti satu hal: **hak paket**, yaitu fitur apa
yang boleh dipakai tenant menurut `plan_type`. Nilainya datang dari
`plan_features` pada respons langganan dan tampil di halaman Subscription, lalu
dipakai `presenly.saas.guard.has_feature()` (§7).

Sebelumnya ada istilah kedua: **katalog endpoint** dari
`GET /v1/presenly/features`, yang menampilkan endpoint mana yang sudah
`available` dan mana yang masih `planned`, beserta menu "Presenly Features" di
Odoo. Katalog itu dihapus di versi 19.0.1.5.0 karena tidak dipakai: tidak satu
pun tombol atau menu memicu penarikannya, sehingga daftarnya selalu kosong,
sementara `has_feature()` bekerja dari data langganan, bukan dari katalog itu.
Endpointnya tetap tersedia di sisi server bagi konsumen lain.

---

### Pengajuan: satu kosakata status, satu bentuk alur

Lima jenis pengajuan dicerminkan dari `/v1/{resource}`: `leaves`, `overtimes`,
`medical-certificates`, `attendance-corrections`, `shift-swaps`. Semuanya
memakai kolom dan kosakata yang sama, karena perbedaan antar jenis adalah sumber
kebingungan yang tidak perlu.

**Dua kosakata status di sisi server.** Lembur memakai penanda lama `Y`/`N`/`T`
(ya, tidak, tunggu); empat jenis lain memakai `pending`/`approved`/`rejected`.
Keduanya dipetakan ke satu kosakata di Odoo:

| Nilai dari Presenly | `status` di Odoo |
| --- | --- |
| `Y` | `approved` |
| `N` | `rejected` |
| `T` | `pending` (bukan `rejected`: `T` berarti "tunggu") |
| `pending`, `approved`, `rejected` | apa adanya |

Nilai aslinya **tidak dibuang**: tersimpan di `status_raw`. Nilai yang belum
dikenal tidak ditebak — `status` dibiarkan kosong dan nilai aslinya tetap
terlihat, bukan menjadi status yang kebetulan mirip. Tanpa pemetaan ini,
penyaring `status = 'approved'` pada lembur tidak pernah cocok karena kolomnya
berisi `Y`, dan itu tidak terlihat sebagai galat: hanya sebagai daftar yang
selalu kosong.

**Alur persetujuan berjenjang.** Payload pengajuan membawa blok `approval`:

```json
{
  "has_workflow": true,
  "status": "pending",
  "current_level": 2,
  "total_levels": 2,
  "steps": [
    {
      "level": 1,
      "status": "approved",
      "expected": {"type": "direct_manager", "value": null, "user": null},
      "acted_by": {"id": 9, "nopeg": "iksg-boss", "name": "boss"},
      "acted_at": "2026-09-21T01:00:00.000Z",
      "rejection_reason": null
    },
    {
      "level": 2,
      "status": "pending",
      "expected": {"type": "role", "value": "hrd", "user": null},
      "acted_by": null, "acted_at": null, "rejection_reason": null
    }
  ]
}
```

Tiap level digabung dari dua sumber: `expected` dari konfigurasi alur (siapa
yang **seharusnya** memutuskan) dan `acted_by` dari langkah yang sudah dijalani
(siapa yang **sudah** memutuskan). Keduanya dipisah karena pengguna perlu tahu
level mana yang belum bergerak, bukan hanya level mana yang sudah selesai.

Approver bertipe `user` disimpan Presenly sebagai id pengguna, dan id itu tidak
bisa dibaca manusia. Karena itu server mengirimnya sebagai orang
(`{id, nopeg, name}`), dan `expected.value` dikosongkan. Aturan yang sama
berlaku untuk `direct_manager`, yang tidak memakai nilai sama sekali.

Di Odoo, tiap pengajuan menyimpan ringkasannya (`approval_has_workflow`,
`approval_flow_status`, `approval_current_level`, `approval_total_levels`, dan
`approval_waiting_for` = siapa yang sedang ditunggu) dan tiap levelnya sebagai
baris anak di `presenly.saas.approval.step.<jenis>`, sehingga bisa disaring,
dikelompokkan, dan dilihat per level.

`acted_at` hanya diisi `action_at`, tanpa jatuh ke `updated_at`. Level yang
masih menunggu belum dikerjakan siapa pun; mengisinya dengan waktu sentuh
terakhir membuatnya terbaca seolah sudah diputus.

### Bagian Persetujuan selalu tampil

Sempat bagian ini disembunyikan saat jenis pengajuannya belum punya alur, dengan
alasan "yang kosong tidak perlu terlihat seperti yang rusak". Itu salah, dan
salahnya baru terlihat di tenant yang sebenarnya:

- **Presenly punya dua sumber keputusan.** Selain alur berjenjang, tiap pengajuan
  menyimpan keputusannya sendiri di kolomnya (`approved_by`, `approved_at`,
  `rejected_at`, `rejection_reason`). Tenant yang belum menyiapkan alur tetap
  punya keputusan — dan itulah yang disembunyikan.
- **Menu tidak menampilkan apa pun, tanpa galat.** Yang terlihat bukan kekosongan
  yang jelas, melainkan tidak adanya bagian itu sama sekali. Tidak ada yang bisa
  dibaca pengguna untuk tahu bahwa datanya memang tidak ada.

Sekarang bagiannya selalu tampil, dan keadaannya ditulis dengan kata:

| Keadaan | Yang tampil |
| --- | --- |
| Ada alur | Ringkasan alur, rangkaian langkah bernomor (§9e), lalu kolom keputusan pengajuannya |
| Ada keputusan, tanpa alur | Kolom keputusan, dan catatan bahwa tidak ada level yang tercatat |
| Belum ada apa pun | Kolom keputusan (kosong), dan catatan "belum ada persetujuan yang tercatat" |

Dua catatan itu dipisah karena keduanya berarti hal berbeda: pengajuan yang belum
diputus tidak boleh terbaca seolah sudah ada keputusan.

Satu grup datar, bukan dua kolom bersarang: jumlah kolom alur berubah mengikuti
ada atau tidaknya alur, dan kolom bersarang akan menyisakan sel kosong di separuh
baris.

### Waktu keputusan tiap level

Nama penyetujunya saja tidak cukup disebut riwayat — tanpa waktunya, urutan
keputusan tidak bisa dipastikan. Dua kolom sempat tertinggal karena hanya namanya
yang dicerminkan, padahal server mengirimnya:

| Jenis pengajuan | Kolom waktu dari server |
| --- | --- |
| Surat dokter, cuti, tukar shift | `approved_at` |
| Koreksi presensi | `tl_approved_at`, `manager_approved_at` |
| Lembur | tidak ada di server; dibiarkan kosong, tidak diisi waktu lain |

### `form` wajib ada di `view_mode`

Action lembur sempat tidak memasang `form`, sehingga formnya **tidak bisa dibuka
sama sekali**: mengeklik baris di daftar hanya mengembalikan ke daftar, tanpa
pesan apa pun. Seluruh isi form itu — termasuk bagian Persetujuan — jadi tidak
pernah terlihat. `tests/test_approval.py` memeriksa `view_mode` kelima action dan
memastikan kepala grup `Approval` tidak lagi memasang `invisible`.

---

### Cermin segar saat halamannya dibuka

Cermin disegarkan **saat daftarnya dibuka**, bukan hanya oleh cron harian. Yang
ditarik hanya yang berubah sejak penarikan sebelumnya (`updated_since`), jadi
yang dibandingkan adalah `updated_at` di sisi server — bukan tanggal bisnis
datanya.

Cakupannya **seluruh data yang dicerminkan**, bukan hanya pengajuan: absensi yang
baru di-tap dari aplikasi, timesheet, pengajuan, rekap bulan berjalan, dan
cermin referensi. Semuanya ikut lewat satu pemicu yang sama.

Bedanya penting. Penarikan rentang menyaring kolom tanggal masing-masing jenis
(`leave_date`, `date`, `requester_date`, …), sehingga koreksi presensi untuk
bulan lalu atau tukar shift untuk bulan depan **tidak pernah ikut terambil**.
Penarikan tambahan tidak punya lubang itu: yang menentukan hanyalah kapan
barisnya berubah.

| Bagian | Irama | Cakupan |
| --- | --- | --- |
| **Pemeriksaan saat halaman dibuka** | setiap kali daftar cermin dibuka | satu permintaan: jenis mana yang berubah |
| Penarikan menyusul | hanya untuk jenis yang berubah | pengajuan, timesheet, log presensi, rekap, referensi |
| `Presenly SaaS: Sync Recent Data` | 15 menit, bisa dimatikan | semuanya, tanpa referensi |
| `Presenly SaaS: Pull Period Data` | harian | presensi, rekap, pengajuan, timesheet — 2 bulan, **dan referensi** |
| Tombol **Pull Period Data** (Subscription) | manual | satu bulan pilihan |

Baris pertama yang membuat data baru **langsung terlihat**, dan ia bekerja tanpa
ambang waktu sama sekali:

1. Daftar cermin dibuka → **satu** permintaan ke `GET /v1/presenly/changes`:
   untuk tiap jenis, waktu perubahan terakhirnya.
2. Jenis yang perubahannya lebih baru dari penanda terakhir ditarik. Yang tidak
   berubah tidak disentuh.
3. Kalau tidak ada yang berubah — yang paling sering terjadi — selesai dengan satu
   permintaan.

Tanpa langkah 1, "periksa setiap kali halaman dibuka" berarti tujuh penarikan
penuh untuk sesuatu yang jawabannya biasanya "tidak ada yang berubah". Dengan
langkah 1, biayanya satu permintaan kecil, jadi tidak ada lagi alasan menahan
pemeriksaannya dengan ambang waktu.

Yang tercatat di sisi server, misalnya: absen keluar diubah pukul 03:01, daftar
Presensi dibuka sekali pukul 03:02, dan Odoo sudah menampilkan waktu yang baru —
dua panggilan penarikan (log presensi dan rekap), bukan tujuh.

Hanya halaman **pertama** yang memeriksa. Menggulir, mengurutkan ulang, dan
mencari memanggil pembacaan yang sama, dan tanpa syarat itu satu kali membuka
daftar yang panjang bisa memeriksa belasan kali. Saklar **Refresh on Open** di
Settings mematikannya sama sekali.

Cermin referensi punya irama sendiri — sejam — karena isinya jarang berubah.
Sebelum ini ia **tidak pernah** ikut penarikan terjadwal sama sekali: hanya tombol
di halaman Subscription yang bisa menariknya.

Empat hal yang membuat pemicu dari halaman ini aman:

1. **Berjalan di transaksi tersendiri.** `web_search_read` ditandai
   `@api.readonly`, sehingga cursornya bisa hanya-baca dan tulisan dari sana
   ditolak PostgreSQL. Transaksi tersendiri itu juga di-commit sendiri, dan hasilnya
   tetap terlihat oleh pembacaan daftar sesudahnya (PostgreSQL membaca dengan
   READ COMMITTED).
2. **Penjagaan waktu, bukan penekanan tombol.** Paling sering sekali per N menit
   per perusahaan, dan penjagaan itu dibaca dari **log sinkronisasi**: percobaan
   yang gagal pun tercatat, sehingga server yang sedang tidak bisa dihubungi tidak
   dicoba ulang oleh setiap halaman yang dibuka. Nilainya bukan disimpan di kolom
   konfigurasi, karena menulisnya berarti menunggu kunci baris yang mungkin
   dipegang transaksi pemanggil — halaman tidak boleh menunggu kunci.
3. **Kuncinya "try", bukan tunggu.** Kalau ada penarikan yang sedang berjalan,
   pemanggil berikutnya langsung menyerah.
4. **Kegagalannya tidak pernah sampai ke halaman.** Server Presenly yang mati
   berarti daftarnya menampilkan cermin apa adanya — bukan halaman yang gagal
   dibuka. Batas waktunya pun dipendekkan jadi 3 detik untuk jalur ini, dan
   percobaan ulang dimatikan supaya halaman tidak menunggu berlipat.

Yang **tidak** bisa dilakukan pemicu ini, dan karena itu tombolnya tetap ada:
melengkapi bulan lama, dan mencoba ulang setelah gagal berulang. Tombol
**Pull Period Data** di halaman Subscription mengerjakan keduanya.

#### Kenapa cron dan tombolnya tidak dihapus

Pemicu dari halaman menjawab "data segar saat saya lihat". Dua hal tetap tidak
bisa dijawabnya, dan keduanya bukan pelengkap:

- **Data yang tidak pernah dilihat siapa pun.** Laporan, ekspor, dan surel
  dihitung dari cermin. Kalau tidak ada yang membuka daftarnya, cerminnya tidak
  pernah diperbarui — dan laporan akhir bulan bisa kehilangan hari terakhir.
  Cron yang mengerjakannya, dan ia bisa dimatikan lewat **Scheduled Refresh**
  (0 = mati) kalau memang tidak diinginkan. Perlu dicatat: ia juga satu-satunya
  yang menangkap **penghapusan** di sisi server, karena pemeriksaan perubahan
  hanya melihat waktu perubahan baris yang masih ada.
- **Penarikan pertama yang besar.** Penarikan tambahan dibatasi 10 halaman.
  Untuk instalasi baru dengan ribuan baris presensi, penarikan pertama akan
  terpotong — dan itu dilaporkan, bukan didiamkan. Tombol **Pull Period Data**
  ada untuk menariknya per bulan.

#### Dua hal yang membuat pemicu ini sempat tidak berjalan sama sekali

Keduanya tidak memunculkan galat apa pun, jadi keduanya ditulis di sini:

1. **Tidak semua cermin mewarisi `presenly.saas.mirror.mixin`.** Log presensi dan
   rekap punya radas penulisan sendiri, sehingga pemicu yang dipasang di mixin itu
   tidak berlaku di sana — membuka daftar presensi tidak menarik apa pun. Keduanya
   sekarang memasang penimpaan `web_search_read` sendiri dan memanggil
   `_refresh_from_page()` yang sama dengan mixin.
2. **Nilai bawaan kolom baru tidak berlaku pada instalasi yang sudah ada.**
   `request_sync_minutes` ditambahkan dengan bawaan 5 menit, tetapi baris
   konfigurasi yang sudah terpasang mendapat **0** — dan 0 berarti pemicunya
   dimatikan.
3. **Halaman Settings mematikannya lagi setiap kali disimpan.** Field di halaman
   itu compute/inverse, dan compute-nya tidak mengisi field `request_sync_minutes`
   — sehingga halaman itu menampilkan 0, dan menyimpannya menulis 0 kembali ke
   konfigurasi. Compute-nya diperbaiki, dan ada tes yang mengunci putaran
   tampil→simpan itu.

---

## 4c. Penarikan terjadwal & jendela bergulir

Dua cron, keduanya hanya bekerja pada koneksi yang **aktif dan bercentang
`enabled`**:

| Cron | Jadwal | Isi |
| ---- | ------ | --- |
| `Presenly SaaS: Refresh Subscription` | harian | memperbarui snapshot langganan |
| `Presenly SaaS: Pull Period Data` | harian | menarik presensi + pengajuan |
| `Presenly SaaS: Clean Up Mirrored Data` | mingguan | menghapus cermin yang sudah tua |

Ketiganya dipisah dengan sengaja. Langganan yang tidak terjangkau tidak berarti
presensi tidak bisa ditarik, dan sebaliknya; satu tenant yang gagal tidak pernah
menghentikan tenant lain. Kegagalan dilaporkan ke log Odoo, bukan dilempar.

**`Bulan yang Ditarik Cron`** = berapa bulan ke belakang yang dicakup penarikan
harian, dihitung mundur dari bulan berjalan. Bawaannya 2, bukan 1: shift yang
berakhir lewat tengah malam, atau koreksi presensi yang diajukan besoknya, masih
masuk ke bulan berikutnya. Menarik hanya bulan berjalan akan melewatkannya.

**`Penyimpanan (bulan)`** = jendela bergulir. Cermin berperiode yang lebih tua
dari ini dihapus oleh pembersihan mingguan. `0` berarti simpan semuanya.

Yang **tidak pernah** dihapus adalah cermin referensi (lokasi kerja, shift, mode
absen, hari libur, setup hari kerja). Isinya keadaan terkini, bukan riwayat;
menghapusnya berdasarkan umur justru membuang data yang masih berlaku.

Rekap dibandingkan sebagai **nomor bulan berjalan** (`tahun * 12 + bulan`), bukan
sebagai pasangan `(tahun, bulan)` yang diurut mentah. Alasannya: Desember 2025
harus dianggap lebih tua dari Januari 2026, walaupun `12 > 1`.

Wizard penarikan manual memberi tahu bila rentang yang diminta lebih tua dari
jendela penyimpanan — data itu akan ditarik sekarang lalu dihapus lagi oleh
pembersihan mingguan, dan lebih berguna diberitahukan daripada terlihat hilang
tanpa sebab.

---

## 4d. Cabang pada pengajuan, dan pemisahan per perusahaan

Pengajuan (cuti, lembur, surat sakit, koreksi presensi, tukar shift) berisi
`location {id, name}` di payloadnya, **tanpa klien**. Padahal untuk payroll yang
perlu diketahui bukan lokasinya, melainkan cabangnya, karena cabang itulah yang
membayar.

Karena itu cabangnya **diturunkan**, bukan ditebak:

| Langkah | Keterangan |
|---|---|
| 1 | Payload pengajuan menyimpan `location.id` di kolom `location_id` |
| 2 | Id itu dicocokkan ke cermin lokasi kerja lewat `external_id`, satu pencarian per tarikan, bukan per baris |
| 3 | Cabang lokasi itu (`internal_company_id`, `internal_company_name`) disalin ke baris pengajuannya sebagai `tenant_client_id` dan `tenant_client_name` |
| 4 | Perusahaan Odoo dari cabang itu (`res.company` dengan `presenly_client_id` yang sama) disalin sebagai `tenant_client_company_id` |

Aturan yang dipegang, dan alasannya:

- **Lewat id, bukan nama.** Nama lokasi bisa diubah di Presenly; id tidak.
- **Sekali isi.** Cabang hanya diisi kalau masih kosong. Pengajuan adalah catatan
  masa lalu: kalau lokasinya suatu saat berpindah klien, baris lama tetap memakai
  klien saat pengajuan itu terjadi. Penarikan memakai `_mirror_upsert`, jadi
  barisnya diperbarui, bukan dibuat ulang; penggantian menyeluruh memang membuat
  ulang, dan di sana cabangnya wajar diturunkan lagi.
- **Kosong kalau lokasinya belum tercermin.** Tidak ditebak, dan jumlahnya
  dilaporkan di log. Cabang yang salah lebih berbahaya daripada cabang yang
  kosong, karena yang salah tidak terlihat.
- **Isi lama tidak perlu API.** Baris yang ditarik sebelum kolom ini ada diisi
  dari `raw_payload` yang tersimpan, lewat migrasi `19.0.2.3.0`.
- **Koreksi presensi dan tukar shift tidak punya lokasi** di payloadnya, jadi
  cabangnya dibiarkan kosong. Kalau nanti diperlukan, sumbernya harus pegawai,
  dan itu ditandai berbeda supaya tidak tertukar dengan yang pasti.

Sejak Presenly mengirim klien lokasi di dalam payload pengajuan
(`location.internal_company`), klien itu dipakai lebih dulu dan pencocokan ke
cermin lokasi hanya menjadi cadangan. Urutannya sengaja begitu: payload adalah
catatan saat pengajuan dibuat, sedangkan cermin lokasi bisa saja sudah berpindah
klien sejak itu. Untuk baris lama yang payloadnya belum memuat klien, jalur
cadangannya tetap bekerja seperti sebelumnya.

Pemisahan **per cabang** dijalankan lewat tiga aturan per model, dan ketiganya
memang diperlukan:

| Aturan | Berlaku untuk | Domain | Alasan |
|---|---|---|---|
| Cabang | pengguna internal | `tenant_client_company_id in company_ids` | Baris cermin berada di perusahaan pusat, jadi aturan perusahaan biasa akan menyembunyikannya dari pengguna cabang. Yang dibandingkan adalah **perusahaan** cabangnya, bukan id kliennya: dua tenant bisa punya id klien yang sama |
| Pengelola | grup Manager | `company_id in company_ids` | Seluruh cabang **di perusahaan yang ia diizinkan**; `company_ids` di situ adalah pagar tenant-nya |
| HR | grup HR | idem | Keputusan pemilik: lintas cabang hanya untuk HR di perusahaan pusat. Aturannya di `presenly_saas_hr`, karena modul ini dipakai juga tanpa HR |

Baris yang cabangnya belum diketahui hanya terlihat oleh pengelola dan HR. Sengaja:
baris tanpa cabang bisa milik cabang mana pun, jadi menampilkannya ke semua orang
berarti membocorkan cabang lain. Jumlahnya dilaporkan di log supaya bisa
ditindaklanjuti, dan kolom perusahaan cabang itu yang nanti dipakai payroll.

### Lokasi dan pegawai sebagai relasi

Cabang saja tidak cukup untuk payroll: yang dihitung adalah lembur **seorang
pegawai** di **sebuah lokasi kerja**. Karena itu pengajuannya juga menyimpan tiga
relasi:

| Kolom | Menunjuk ke | Cara mencocokkan |
|---|---|---|
| `tenant_location_id` | `presenly.saas.work.location` | `location.id` payload ke cermin lokasi (`external_id`) |
| `hr_work_location_id` | `hr.work.location` | `presenly_external_id` lokasi itu |
| `hr_employee_id` | `hr.employee` | nomor pegawai (`nopeg`) lewat cermin pegawai |

Ketiganya ada di `presenly_saas_hr`, bukan di `presenly_saas`, sebab semuanya
menyentuh model HR. Kalau lokasinya punya perusahaan yang sama dengan cabang
barisnya, lokasi itulah yang dipilih; kalau tidak ada yang cocok, kolomnya
dibiarkan kosong dan jumlahnya dilaporkan di log. Mencocokkan lokasi berdasarkan
nama sengaja tidak dilakukan: di lapangan ada lokasi bernama sama di dua cabang,
dan payroll akan menagih lembur ke cabang yang salah tanpa ada yang menyadarinya.

### Yang payroll butuhkan dari baris ini

`hr_payroll_custom` **tidak diubah** oleh pekerjaan ini. Yang disiapkan hanya
datanya, dan kontraknya empat kunci - persis yang sudah dipakai
`_presenly_overtime_domain` di modul payroll:

| Kunci | Sumber di cermin lembur |
|---|---|
| `employee_id` | `hr_employee_id` |
| `state` | `status` (`approved`) |
| rentang tanggal | `overtime_date`, plus `start_time` dan `end_time` untuk jamnya |
| `work_location_id` | `hr_work_location_id` |

Keempatnya dibuktikan bisa dijawab dari baris cermin oleh
`tests/test_submission_payroll_ready.py`. Jadi ketika payroll mulai menyaring per
lokasi, yang perlu ditambahkan hanya penyaringnya - bukan kolom baru di sini.

## 4e. Kolom proyek cermin presensi

Kolom Project pada form Detail Data Presensi pernah menampilkan repr payload:

```
{'id': 3, 'project_name': 'MAMBU KECUT', 'project_code': '987364', 'client': ...}
```

Sebabnya satu baris: `employee.get('project')` - sebuah objek - diserahkan apa
adanya ke kolom `Char`. Odoo menyimpan repr-nya, dan tidak ada yang mengeluh
karena hasilnya tetap "ada isinya". Yang menemukannya adalah pemilik data, dari
layar, bukan dari uji.

Sekarang objeknya dipisah menjadi `project_code` dan `project_name`, dan yang
ditampilkan satu kolom `project_label` berbentuk `[KODE] Nama`. Nama diambil dari
`project_name` dengan `name` sebagai cadangan, karena resource lokasi dan resource
pegawai menyebutnya berbeda. Proyek yang datang bukan sebagai objek **tidak**
disimpan sebagai teks mentah: kolomnya dibiarkan kosong dan kejadiannya dicatat di
log - menampilkan JSON dengan cara lain bukan perbaikan.

Baris lama diperbaiki migrasi `19.0.2.5.0` dari `raw_payload` yang tersimpan.
Yang disentuh hanya baris yang kolomnya masih berbentuk repr (diawali `{`), jadi
nama proyek yang sudah disunting orang tidak tertimpa. Baris rusak yang payload-nya
tidak memuat proyek dikosongkan, dan jumlahnya dilaporkan di log.

Kolomnya sengaja hanya kode, nama, dan labelnya. Sebuah relasi ke cermin proyek
(`presenly.saas.project`) sempat ditambahkan, lalu dibuang lagi: kode dan namanya
sudah tersimpan di barisnya sendiri, dan kolom relasinya hanya menggandakan kolom
yang sama di layar. Cermin proyeknya sendiri tetap ada dan tetap dipakai halaman
Projects; yang tidak diperlukan adalah tautan dari log presensi ke sana.

Daftar dan form menampilkan `project_label` - kode dan nama dalam satu kolom -
dengan `project_code` sebagai kolom opsional, dan `project_name` sebagai kunci
group by.

## 4f. Siapa melihat apa

Menu akar Presenly SaaS sebelumnya hanya untuk Manager, dan cermin presensi tidak
punya aturan akses sama sekali. Dua hal itu bersama membuat data tidak bisa dipakai
oleh orang yang paling membutuhkannya: pegawainya sendiri. Perlu ditegaskan bahwa
Odoo **tidak** menambahkan saringan perusahaan sendiri - `company_ids` hanya
variabel yang bisa dipakai di domain - jadi model dengan `company_id` tanpa aturan
menampilkan baris dari semua perusahaan.

Yang berlaku sekarang:

| Siapa | Melihat |
|---|---|
| Pengguna internal | Barisnya sendiri, pada cermin presensi dan kelima jenis pengajuan |
| Approver | Satu cabang, karena dialah yang memutuskan pengajuannya |
| Manager | Seluruh cabang di perusahaan yang ia izinkan |
| HR | Idem, dan ditambah di modul HR karena grupnya hanya ada di sana |

Aturan "milik sendiri" tinggal di `presenly_saas_hr` karena butuh `user.presenly_nopeg`,
dan kolom itu butuh `hr`. Kolom tersebut dibuat karena `res.users.employee_id`
adalah pegawai pada **perusahaan yang sedang aktif**, sedangkan record pegawai di
sini berada di perusahaan integrasi.

Satu keputusan yang mudah "diperbaiki" orang dan justru merusak: aturan "milik
sendiri" **tidak** diberi pagar `company_id in company_ids`. Di basis nyata,
pengguna cabang hanya punya perusahaan cabangnya (`yusril` punya CLIENT 1 dan
CLIENT 2), sedangkan seluruh baris cermin berada di perusahaan integrasi. Pagar itu
akan membuat pegawai cabang kehilangan datanya sendiri. Yang menjaga batas tenant
adalah aturan pengelola, Approver, dan HR, ditambah awalan tenant pada nopeg.

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

## 5c. Integrasi pegawai ada di modul terpisah

Pegawai **tidak** ditangani modul ini. Integrasi dengan `hr.employee` berada di
modul `presenly_saas_hr`.

Pemisahan itu disengaja, dan alasannya bukan kerapian semata:

| | |
|---|---|
| Modul ini dipakai **semua** tenant | HR hanya sebagian |
| Dependensi `hr` menarik `resource`, `resource_mail`, `phone_validation`, dan `mail` | Memaksanya di sini berarti setiap instalasi ikut memuatnya |
| `hr` juga membawa penolakan `hr_attendance` dan `hr_holidays` | Tenant yang tidak memakai HR tidak perlu ikut dibatasi |

Konsekuensi yang perlu diketahui: bila `presenly_saas_hr` dipasang, modul itu
menolak `hr_attendance` dan `hr_holidays` — lihat README modul tersebut.

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

## 8b. Penutupan akses

`Tutup Akses` (`presenly.saas.config.block_mode`) menentukan apa yang terjadi pada
backend saat langganan tidak aktif. Bawaannya `Nonaktif`: pemutakhiran modul tidak
pernah mengunci instalasi yang sudah berjalan.

| Nilai | Yang benar-benar terjadi |
| --- | --- |
| `Nonaktif` | Tidak ada yang ditutup. Banner tetap menjelaskan keadaannya |
| `Uji coba` | Setiap permintaan yang AKAN ditolak dihitung dan dicatat, lalu tetap diloloskan |
| `Wajibkan` | Backend ditutup untuk perusahaan itu, kecuali yang ada di daftar di bawah |

Siapa yang ditutup: pengguna internal (`base.group_user`). Portal dan publik tidak,
karena mereka pelanggan tenant, bukan stafnya. `uid 1` tidak pernah ditutup, dan
manajer tetap bisa memakai halaman blokir walau backendnya tertutup untuknya.
Perusahaan yang diperiksa adalah perusahaan yang sedang dipakai sesi itu.

Yang tetap hidup saat ditutup:

| Jalur | Alasan |
| --- | --- |
| `/web/login`, `/web/session/*` | cara masuk dan keluar, termasuk untuk memperbaiki |
| `/web/assets/*`, `/web/static/*`, `/logo`, `/favicon.ico` | halaman blokir harus tampil utuh |
| `/presenly_saas/blocked*` | halaman penjelasan dan dua jalur perbaikannya |
| `/presenly_saas/webhook/<token>` | cermin tetap segar, dan itu pintu masuk server, bukan manusia |

Yang ditutup termasuk laporan, `/web/dataset/call_kw`, panggilan dengan kunci API,
dan API aplikasi `/api/presenly/v1/*`. Cron tidak tersentuh karena ia bukan
permintaan HTTP, jadi penarikan data tetap berjalan.

Alasan blokirnya konservatif, sama seperti API guard: hanya jawaban nyata dari
server yang menutup akses. Snapshot yang tidak terkonfirmasi baru menutup setelah
`Masa Tenggang` lewat, dan hanya bila tenggangnya diisi. Snapshot yang belum
pernah ada tidak menutup apa pun.

Tiga jalan keluar, dan ketiganya perlu diketahui sebelum menyalakan `Wajibkan`:

| Jalur | Cara | Untuk |
| --- | --- | --- |
| Halaman blokir | **Segarkan langganan**, dan **Ubah koneksi** untuk alamat, tenant code, atau kunci API | manajer, keadaan normal |
| Akses sementara | `Akses Sementara Sampai` + alasannya, dicatat di log sinkronisasi | pendampingan selagi perpanjangan diselesaikan |
| Sekoci | `ir.config_parameter` bernama `presenly_saas_block_disabled` diisi `1` | operator, saat insiden |

Operasi sistem (impor, migrasi, cron internal, tes) lewat dengan context
`presenly_saas_skip_guard=True`. Sekoci `uid 1` juga berlaku untuk itu.

---

## 9. Pengujian

```bash
odoo-bin -d <db> -i presenly_saas \
  --addons-path=odoo/addons,addons,custom_addons \
  --test-enable --test-tags=/presenly_saas \
  --stop-after-init --no-http
```

510 kasus uji pada basis data yang memasang `presenly_saas` **dan**
`presenly_saas_hr` (0 gagal, 0 error):

| Berkas                         | Cakupan                                                                                                  |
| ------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `tests/test_saas_client.py`    | normalisasi URL, header, retry vs tidak retry, skema, redaksi kunci API                                  |
| `tests/test_config.py`         | singleton per perusahaan, constraint, penyegaran, kegagalan tidak mengubah status, cron, pemangkasan log |
| `tests/test_guard_contract.py` | seluruh matriks mode × status, grace, kontrak full access, payload banner                                |
| `tests/test_guard_gate.py` | fungsi keputusan blokir tanpa basis data, kebijakan gerbang (jalur, peran, sekoci, mode), anggaran query, penanda blokir, dan nilai halaman blokir tanpa rahasia |
| `tests/test_guard_http.py` | gerbang lewat HTTP sungguhan: pengalihan `/odoo`, galat JSON-RPC, laporan, jalur yang tetap hidup, halaman blokir untuk staf dan manajer, akses sementara |
| `tests/test_res_config_settings.py` | blok Settings native, pintasan menu Configuration |                                                  
| `tests/test_plan_features.py` | konsumsi paket & fitur, `has_feature()`, `missing_features()` |                                            
| `tests/test_presenly_endpoints.py` | cermin presensi & rekap, paginasi, wizard |                                            
| `tests/test_monitoring.py` | uji silang agregat vs rekap server, penarikan rentang bulan |                                                 
| `tests/test_submissions.py` | pemetaan lima jenis pengajuan, ganti per rentang |
| `tests/test_submission_company.py` | cabang pengajuan diturunkan dari lokasi (lewat id, sekali isi, dibiarkan kosong bila lokasinya belum tercermin), pengisian dari payload lama, dan aturan perusahaan benar-benar menyaring |
| `tests/test_retention.py` | jendela bergulir, cron penarikan, setelan baru, peringatan wizard |
| `tests/test_timesheets.py` | hitungan jam, pemetaan timesheet & proyek, penarikan |
| `tests/test_approval.py` | kosakata status, pemetaan level alur, waktu keputusan, bagian Persetujuan yang wajib tampil, dan syarat pemuatan data widget langkah |
| `tests/test_incremental_sync.py` | penarikan tambahan, penjagaan waktu, dan pemicu dari halaman |
| `tests/test_monitoring_fields.py` | field turunan monitoring (terlambat, jam masuk, jam sesi) dan kolom yang bisa dibaca di form |
| `tests/test_acl_coverage.py` | setiap model punya baris ACL |
| `tests/test_map_widget_registration.py` | skema props widget peta, `onError`, bentuk templat |
| `tests/test_map_widget_options.py` | setiap field pendamping di `options` ada di view, dan peta memakai `colspan="2"` |
| `tests/test_i18n_file.py` | `id.po` terurai, tidak ada `msgstr` kosong, setiap entri punya `#. module:` |

Model (`.py`) yang berubah menuntut server Odoo **dimulai ulang**; perubahan
view, XML, dan `id.po` cukup `-u` lalu muat ulang browser. Perubahan JS/CSS juga
menuntut mulai ulang — lihat bagian berikut.

---

---

## 9b. Aset: kapan perubahan JS sampai ke browser

Odoo menyimpan **isi** bundel aset di cache proses:

```python
tools.ormcache('bundle', 'css', 'js', ..., cache='assets')
```

Akibatnya penting dan sempat menyesatkan: mengubah berkas JS/CSS **tidak** cukup
dengan memuat ulang browser, dan **tidak** cukup dengan `-u <modul>` dari proses
lain. Selama server Odoo yang lama masih hidup, ia terus menyajikan bundel versi
lamanya (`/web/assets/<versi>/web.assets_web.min.js`), sehingga perbaikan yang
sudah ada di berkas terlihat seolah-olah tidak berpengaruh.

Yang harus dilakukan:

| Perubahan | Cukup begini |
|---|---|
| `.py` | mulai ulang server |
| XML view, `id.po`, data | `-u <modul>` lalu muat ulang browser |
| JS, CSS, templat OWL | mulai ulang server |
| ingin memeriksa cepat sambil mengembangkan | jalankan server dengan `--dev=assets` |

Cara memastikan versi bundel yang benar-benar diuji — bandingkan hash di URL
`/web/assets/<hash>/web.assets_web.min.js` dengan yang dihitung proses baru:

```python
env['ir.qweb']._get_asset_bundle(
    'web.assets_web', assets_params={'lang': 'en_US', 'debug': False}
).get_version('js')
```

`--dev=assets` **tidak** mewakili produksi. Templat OWL yang lolos di mode dev
bisa gagal di bundel ter-minify — lihat bagian berikut.

---

## 9d. Form presensi: aturan tata letaknya

Form detail disusun dengan tiga aturan yang berlaku untuk view lain juga —
log presensi dan lokasi kerja memakainya, dan bentuk sebelumnya di kedua form itu
mengulang kesalahan yang sama.

**Yang dibandingkan diletakkan berdampingan, dengan susunan kolom yang sama.**
Titik masuk dan titik keluar berada di satu baris — waktu, mode, jarak, putusan
geofence — bukan tersebar di dua tempat yang harus digulir untuk dibandingkan.
Dua peta juga berdampingan, bukan ditumpuk: ditumpuk, dua peta setinggi 240px
membuat formnya dua kali lebih panjang daripada isinya.

**Kolom tidak boleh menyisakan separuh halaman.** Kelompok dua kolom diisi
seimbang (4 lawan 4, bukan 7 lawan 1), dan kelompok dengan jumlah field ganjil
— seperti sumber data — dibagi lagi menjadi dua kolom di dalamnya. Satu sel
kosong di baris terakhir tidak apa-apa; separuh halaman kosong tidak.

Di form lokasi kerja, bentuk lamanya menaruh lima field geofence berdampingan
dengan satu field alamat; sekarang radius, zona waktu, dan jenis absen di kiri
berhadapan dengan alamat, proyek, dan perusahaan di kanan.

**Peta tanpa `colspan="2"` jatuh ke kolom label.** Peta dengan `nolabel="1"`
tetap menempati satu sel grid, dan sel yang jatuh ke kolom label hanya selebar
150px — kolom nilainya yang lebar justru kosong. Gejalanya: peta kurus memanjang
dengan legenda yang terpotong-potong, dan ubinnya tidak termuat. Dua form yang
memakai widget peta pernah kena, dan keduanya sudah memakai `colspan="2"`.

**Angka mentah tidak ditampilkan di form.** `13587796.00` meter dan `250.00`
meter adalah dua angka yang harus dibandingkan sendiri oleh pembacanya, padahal
jawabannya satu kata:

| Kolom | Isi di form |
|---|---|
| `check_in_distance_meters` (mentah) | tidak ditampilkan; tetap ada di daftar, pivot, dan ekspor |
| `check_in_distance_text` | `13 588 km from the office, allowed 250 m` |
| `check_in_radius_state` | badge `Outside` |
| `late_minutes` (mentah) | `9h 31m late`, atau `On time` |
| `session_hours` (mentah) | `8h 30m` |

Fakta dan putusan dipisah karena keduanya menjawab pertanyaan berbeda: kalimat
jarak menyebut angkanya, badge menyebut kesimpulannya. Badge-nya bisa disaring
(`Outside Geofence`) dan dikelompokkan, dan itu sebabnya `check_in_radius_state`
disimpan (`store=True`) — tanpa itu Odoo tidak bisa menjawab saringan tersebut.

Pemisah ribuan memakai spasi, bukan titik atau koma: keduanya berarti hal
berbeda di dua bahasa yang dipakai modul ini, jadi keduanya menyesatkan di salah
satu bahasa. `m` dan `km` adalah satuan SI, jadi tidak perlu diterjemahkan.

**Nilai yang tidak ada disembunyikan, nilai nol ditulis.** `Session Length`
hilang dari form ketika memang tidak ada lama sesi yang bisa dihitung (check-out
terlewat, atau shift lewat tengah malam) — baris kosong terbaca seperti tampilan
yang rusak. Sebaliknya `Lateness` selalu ditulis, termasuk `On time`: baris
kosong membuat pembaca menebak apakah artinya tepat waktu atau datanya tidak ada.

### Dua mesin ekspresi yang berbeda

Ini pernah menjatuhkan satu form penuh, jadi ditulis di sini:

| Tempat | Mesin | Operator |
|---|---|---|
| `t-if`, `t-att-*`, `t-esc` di templat OWL | JavaScript | `&&`, `||`, `!` |
| `invisible`, `readonly`, `required` di arch view | Python (server) | `and`, `or`, `not` |

Salah satu di tempat yang lain tidak memunculkan galat yang menyebut barisnya:
formnya mati dengan dialog **Oops!**, dan penyebabnya hanya terlihat setelah
detail teknisnya dibuka (`Failed to compile template ... Unexpected identifier`).
Karena itu syarat yang panjang dipindahkan ke getter di JavaScript, dan
`tests/test_map_widget_registration.py` menolak operator Python di ekspresi
templat.

---

## 9c. Widget peta: dua hal yang bukan pilihan gaya

`static/src/map/presenly_map_field.*` menggambar peta Leaflet pada log presensi
dan lokasi kerja.

1. **Leaflet dimuat lewat `loadJS`/`loadCSS`, bukan lewat manifes aset.** Ketika
   ikut dibundel Odoo, Leaflet versi UMD tidak lagi menerbitkan `window.L`.
2. **Templatnya dangkal: satu `t-out` per elemen bersyarat, teks dirakit di
   JavaScript.** Versi yang menaruh teks bercampur `<t t-out>` di dalam elemen
   bersyarat menjatuhkan widget ini di bundel produksi dengan:

   ```
   OwlError: An error occured in the owl lifecycle
   Cause: TypeError: this.child.mount is not a function   (VToggler.mount)
   ```

   Kegagalannya ikut menjatuhkan **seluruh form**, dan pesannya tidak menyebut
   penyebabnya. Karena itu `legendOffice`, `legendPoint`, dan `missingFieldsText`
   dirangkai di JavaScript, memakai `_t()` supaya tetap bisa diterjemahkan.

3. **Legenda hanya menjelaskan yang digambar peta.** Penanda titik memang hanya
   digambar kalau letaknya berbeda dari kantor, tetapi legendanya dulu tetap
   mencantumkan baris titik — titik berwarna kedua yang tidak ada di peta. Kedua
   baris itu kini sejalan: baris titik muncul hanya kalau letaknya berbeda, atau
   kalau ia membawa keterangan yang tidak ada di baris kantor (waktunya, atau
   orangnya). Karena itu tombol pintasan "Office" juga disembunyikan saat titiknya
   sendiri adalah kantornya.

`tests/test_map_widget_registration.py` menjaga ketiganya.

---

## 9e. Widget langkah persetujuan

`approval_step_ids` digambar sebagai rangkaian langkah bernomor yang tersambung —
bukan tabel. Tabel menyembunyikan justru hal yang dicari pembaca: langkah mana
yang sudah lewat, mana yang sedang berjalan, dan mana yang belum tersentuh.

```
① Direct Manager                              [APPROVED]
   Decided by yusril on Sep 22, 9:15 AM
│
② Role hrd                                     [PENDING]     ← disorot
   Waiting for a decision
│
③ Role direktur                                [PENDING]
   Not reached yet
```

Aturan yang dipegangnya:

| Bagian | Aturan |
| --- | --- |
| Rel penghubung | Hijau setelah langkah yang **disetujui**; abu-abu sesudahnya. Langkah yang ditolak sengaja tidak diberi warna: setelah penolakan alurnya berhenti, dan rel berwarna menyiratkan lanjutan yang tidak ada |
| Langkah berjalan | Latar dan lingkaran disorot kuning — satu-satunya langkah yang butuh tindakan |
| Langkah belum tersentuh | Diredupkan, dan keterangannya "Belum sampai di langkah ini" |
| Status asing | Tidak diberi label sama sekali. Lebih baik kosong daripada menyebutnya "Pending" padahal artinya belum tentu itu |
| Tanpa waktu | "Diputuskan oleh X", tanpa tanggal — bukan diisi waktu tarikan |

### Dua syarat yang gagalnya tidak kelihatan

1. **`<list>` di dalam fieldnya harus tetap ada** meski tidak ditampilkan. Odoo
   membaca subview itu untuk menentukan field anak mana yang perlu dimuat; tanpa
   itu widgetnya menerima baris tanpa isi — rangkaian langkah yang kosong, tanpa
   satu pun pesan kesalahan. Dijaga oleh
   `test_approval.py::TestPresenlyApprovalStepsWidget`.
2. **Pembungkus field Odoo (`o_field_<nama widget>`) bersifat `inline-block`**,
   jadi lebarnya menyusut mengikuti isinya. Akibatnya rangkaian langkahnya
   terjepit selebar teks terpanjangnya; `width: 100%` di dalamnya tidak menolong
   karena persentasenya dihitung terhadap pembungkus yang menyusut itu.
   Pembungkusnya diubah menjadi `block` di SCSS widget ini.

---

## 10. Bahasa

String sumber ditulis dalam **bahasa Inggris**; terjemahan Indonesianya ada di
`i18n/id.po` (537 entri). Pengguna memilih bahasa lewat Preferences, dan kedua
bahasa tersedia sekaligus.

Aturan yang dipakai:

| Bagian | Bahasa |
|---|---|
| String yang terlihat pengguna (`.py`, `.xml`) | Inggris — supaya bisa diterjemahkan |
| Terjemahan | `i18n/id.po` |
| Komentar kode dan docstring | Indonesia — untuk tim, tidak pernah tampil |

### Yang wajib diingat saat menambah string

Bungkus setiap teks yang terlihat pengguna dengan `_()`. Ini pernah terlewat:
pesan uji silang di Monitoring Presensi dibangun dari teks Indonesia yang
langsung disambung, sehingga **tidak pernah bisa diterjemahkan** dan tetap
berbahasa Indonesia walau Odoo dijalankan dalam bahasa Inggris.

Di dalam tes, bandingkan teks terjemahan dengan `_()` yang sama seperti modul,
**bukan** `self.env._()`. Alasannya nyata dan sudah terukur: di lingkungan tes
`env.lang` bernilai kosong, jadi `self.env._()` mengembalikan teks sumber apa
adanya, sementara `_()` mengikuti bahasa pengguna. Tes yang memakai
`self.env._()` akan lulus di satu bahasa dan gagal di bahasa lain.

`id.po` tidak memuat entri yang terjemahannya sama dengan sumbernya. Istilah yang
memang sama di dua bahasa (`Latitude`, `Status`, `Tenant`, nama bulan seperti
`April`) sengaja tidak punya entri: Odoo menampilkan teks sumbernya, dan itu sudah
benar. Karena itu jumlah entri selalu lebih kecil dari jumlah string sumber.

Berkas `i18n/en.po` tidak dibuat karena string sumbernya sudah bahasa Inggris.

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
├── migrations/     pemetaan data saat naik versi
├── models/         config, subscription, sync log, guard, fitur eksternal,
│                   cermin presensi, rekap, referensi, pengajuan & timesheet,
│                   kosakata status dan alur persetujuan berjenjang
├── security/       group, ACL, record rule multi-company
├── services/       klien HTTP (tanpa dependensi Odoo, mudah diuji)
├── static/         ikon + komponen OWL banner dan peta
├── tests/          510 kasus uji (kedua modul)
├── views/          form, list, search, menu
└── wizard/         pemilih periode penarikan (presensi + pengajuan)
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
| Status pengajuan diseragamkan di Odoo, bukan di API | API mencerminkan nama kolom server; pemetaan dua kosakata diletakkan di tempat keduanya bertemu, dan nilai aslinya tetap disimpan |
| Level alur digabung dari konfigurasi dan langkah nyata | `expected` menjawab "siapa yang seharusnya", `acted_by` menjawab "siapa yang sudah"; memisahkannya membuat level yang belum bergerak tetap terlihat |
| `acted_at` tidak jatuh ke `updated_at` | Level yang masih menunggu belum dikerjakan siapa pun; mengisinya membuatnya terbaca seolah sudah diputus |
| Kelima pengajuan memakai model langkah sendiri | Satu One2many yang benar per jenis lebih terbaca daripada kunci polimorfik, dan hak aksesnya tetap eksplisit |

## 8. Klien Presenly menjadi perusahaan Odoo

Sinkronisasi awal hanya mencerminkan data presensi. Bagian ini menambahkan arah yang
lain: **klien di Presenly menjadi `res.company` di Odoo**, sehingga pegawai bisa
memiliki perusahaan yang benar tanpa diketik manual.

Setelannya `Create Companies from Clients`, **mati secara bawaan**. Alasannya bukan
teknis: perusahaan adalah entitas akuntansi. Membuatnya sebagai efek samping
sinkronisasi presensi berarti membuat buku yang tidak diminta siapa pun.

Perusahaan yang dibuat **tidak pernah dihapus otomatis**. Klien yang hilang dari
respons hanya dilaporkan lewat log (`missing`) — menghapus `res.company` akan
membawa data akuntansi yang menggantung padanya.

Catatan yang mahal untuk ditemukan: **hierarki perusahaan tidak bisa diubah setelah
dibuat.** `res.company.write` menolak dengan *"The company hierarchy cannot be
changed"*. Rencana awal untuk menaruh perusahaan klien di bawah perusahaan pemasang
gagal karena itu, dan percobaan itu sempat merusak penarikan klien. Yang dipakai
sekarang: perusahaan klien berdiri sendiri, dan pencarian konfigurasi untuk kirim
balik memakai `_config_for_company()` — naik ke induk bila ada, lalu jatuh ke
konfigurasi aktif **hanya bila tunggal**. Kalau ada lebih dari satu konfigurasi
aktif, kirim baliknya ditolak dan dilaporkan, karena menebak berisiko mengirim data
ke tenant Presenly yang salah.

## 9. Rekonsiliasi

Sinkronisasi yang gagal tidak berbunyi: webhook bisa tidak sampai, cron bisa
melewatkan perubahan yang stempel waktunya tidak jujur, dan tarikan bisa menimpa
suntingan Odoo tanpa suara. Rekonsiliasi membandingkan **isi sebenarnya**, bukan
mempercayai salah satu pihak yang mengaku sudah berubah.

Yang **tidak** dilakukannya, dan itu keputusan sadar: ia tidak membereskan apa pun
sendiri. "Nilai mana yang benar" bergantung pada siapa pemilik kolom itu — radius
geofence milik aplikasi, nama lokasi bisa jadi milik Odoo karena bagian legal yang
menggantinya. Menebak berarti menimpa nilai yang benar dengan yang salah, dan kali
ini juga tanpa suara. Jadi alat ini melapor dan membiarkan manusia memutuskan.

Sisi Presenly dari perbandingan adalah **cermin terakhir**, bukan panggilan API baru.
Cermin menyimpan nilai yang diterima apa adanya, termasuk yang gagal diterapkan ke
model native — persis yang perlu dilihat. Waktu penyegaran terakhirnya ikut
ditampilkan supaya kebasiannya tidak tersembunyi.

Tiga sifat yang dijaga, dan semuanya pernah rusak saat pengembangannya:

| Sifat | Kenapa |
|---|---|
| Tiap dataset diperiksa terpisah | Perbandingan klien butuh jaringan, lokasi dan pegawai tidak. Sebelum dipisah, satu kegagalan jaringan membatalkan **seluruh** pemeriksaan — persis kegagalan diam yang alat ini ada untuk mencegahnya |
| Dataset yang gagal tidak ikut ditutup | Pemeriksaan yang tidak sempat berjalan bukan bukti bahwa bedanya sudah selesai |
| Temuan diperbarui, bukan ditumpuk | Satu kolom satu baris, dijaga constraint unik. Tanpa itu, pemeriksaan harian akan mengubur laporannya sendiri |

Temuan yang bedanya hilang menutup sendiri (`resolved`), tetapi keputusan manusia
(`ignored`) tidak dibatalkan oleh pemeriksaan berikutnya. Temuan yang muncul lagi
setelah ditutup akan terbuka kembali — menyembunyikannya justru yang mau dihindari.
