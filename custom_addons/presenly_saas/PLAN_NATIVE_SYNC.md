# Plan: sinkronisasi ke model native Odoo (company, lokasi kerja, pegawai)

Status: rencana, belum dikerjakan.
Permintaan: data klien Presenly masuk ke `res.company` bawaan Odoo, setup multi
lokasi ikut tersinkron ke modul Odoo, dan sinkronisasinya **real-time dua arah
antar host** — bukan cron.

---

## 0. Ringkasan

Tiga hal yang berbeda tingkat kesiapannya:

| Yang diminta | Keadaan sekarang |
| --- | --- |
| Pegawai → `hr.employee` | **sudah ada** (`presenly_saas_hr`), dua arah, dipicu webhook + tombol |
| Lokasi kerja → `hr.work.location` | belum; sekarang hanya cermin sendiri (`presenly.saas.work.location`) |
| Klien Presenly → `res.company` | belum; sekarang hanya cermin (`presenly.saas.internal.company` lewat resource `internal-companies`) |

Real-time dua arah untuk pegawai **sudah jalan** dan bukan lewat cron: Presenly
memanggil Odoo lewat webhook, dan Odoo memanggil Presenly setelah transaksi commit.
Yang belum: cakupan peristiwanya (baru pegawai), dan dua model baru di atas.

---

## 1. Temuan

### 1a. Model native yang jadi tujuan

```
hr.work.location                      hr.version (diwarisi hr.employee)
  name            required              work_location_id  M2o hr.work.location
  company_id      required              department_id    M2o hr.department
  location_type   required, default     job_title        Char
                  'office'              address_id       M2o res.partner
  address_id      M2o res.partner
                  REQUIRED
  location_number Char
  active          Boolean
```

Dua hal yang menentukan rancangan:

- **`hr.work.location` mewajibkan `address_id`** — jadi tiap lokasi Presenly perlu
  pasangan `res.partner` lebih dulu. Alamat di Presenly berupa teks bebas
  (`address`), bukan komponen terpisah, jadi yang bisa diisi hanya `name` partner
  dan `street` mentah.
- **Di Odoo 19 lokasi kerja pegawai ada di `hr.version`, bukan `hr.employee`** —
  model pegawai punya versi, dan field seperti `work_location_id`,
  `department_id`, `job_title`, `address_id` tinggal di sana lalu diwarisi. Sync
  yang menulis ke `hr.employee` tetap bekerja (diteruskan ke versi aktif), tetapi
  bacaannya harus lewat field warisan itu, dan **satu pegawai bisa punya beberapa
  versi** — mana yang dianggap berlaku perlu diputuskan.

### 1b. Bentuk data di Presenly

```
internal-companies   id, name, email, whatsapp_number, business_sector
                     (tidak ada alamat dan tidak ada kode)

work-locations       id, name, address, latitude, longitude, radius_meters,
                     timezone, attendance_type, is_active
                     + internal_company {id, name}   ← klien pemiliknya
```

`work-locations` **tidak** membawa `internal_companies` ID mentah; API mengirimnya
sebagai objek `internal_company`. Jadi penautan lokasi ke klien tersedia, dan itu
yang membuat lokasi bisa dikelompokkan per perusahaan di Odoo.

### 1c. Kanal real-time yang sudah ada

| Arah | Cara | Catatan |
| --- | --- | --- |
| Presenly → Odoo | webhook `POST /presenly_saas/webhook/<token>` | HMAC-SHA256, toleransi ±300 detik; isi payload **isyarat saja** (tanpa PII) |
| Odoo → Presenly | `POST`/`PATCH /v1/employees` | dijalankan setelah commit; dibandingkan **berdasarkan nilai**, bukan jam |

Pendaftaran webhook menyimpan **satu alamat per tenant** — jadi menambah peristiwa
baru berarti menambah jenis peristiwa pada satu penerima, bukan menambah penerima.

---

## 2. Rancangan

### 2a. Klien Presenly → `res.company`

Satu pertanyaan yang harus Anda jawab lebih dulu, karena arahnya menentukan
seluruh rancangan:

| Tafsir | Artinya | Akibat |
| --- | --- | --- |
| **A. Tiap klien jadi satu perusahaan Odoo** | Odoo menjadi multi-company; tiap klien punya chart of accounts, pajak, dan aturan sendiri | benar secara akuntansi, tetapi Odoo akan membuat perusahaan lengkap secara otomatis — keputusan besar, dan sulit dibatalkan |
| **B. Klien jadi `res.partner` bertanda perusahaan** | Satu perusahaan Odoo; klien adalah relasi | jauh lebih ringan, tetapi tidak memberi pemisahan data antar klien |
| **C. Klien tetap cermin, hanya namanya ditautkan** | seperti sekarang, ditambah relasi ke partner | paling ringan, tetapi tidak memenuhi permintaan "masuk ke company bawaan Odoo" |

Usulan saya **A, tetapi dengan pengaman**: perusahaan dibuat sekali, tidak pernah
dihapus otomatis, dan pembuatannya bisa dimatikan lewat setelan. Alasannya: kalau
tujuannya memisahkan data per klien, `res.company` memang alatnya di Odoo, dan
`check_company` pada `hr.work.location` serta `hr.version` menuntut perusahaannya
benar-benar ada.

Yang diisi dari Presenly: `name`, `email`, dan `phone` (dari `whatsapp_number`).
`business_sector` tidak punya padanan native; ia disimpan di kolom sampingan pada
perusahaan, bukan dipaksakan ke field yang artinya berbeda.

### 2b. Lokasi kerja → `hr.work.location`

Per lokasi, urutan kerjanya:

1. `res.partner` — dibuat atau diperbarui (nama lokasi + `street` dari alamat teks),
   milik perusahaan yang sesuai.
2. `hr.work.location` — nama, `company_id` dari klien pemiliknya, `location_type`
   `'office'` (Presenly hanya punya lokasi bergeofence), `address_id` ke partner tadi.
3. **Geofence tidak ada padanannya di Odoo** (tidak ada koordinat maupun radius).
   Karena itu `hr.work.location` diperluas lewat modul bridge dengan field
   `presenly_*`: `external_id`, `latitude`, `longitude`, `radius_meters`,
   `timezone`, `attendance_type`, `synced_at`. Ini melanggar aturan lama modul
   ("tidak mewarisi model bisnis native") — aturan itu dibuat untuk presensi,
   sedangkan di sini permintaannya justru integrasi native. Perluasannya memakai
   awalan `presenly_`, jadi tidak bertabrakan dengan field Odoo.
4. Cermin `presenly.saas.work.location` tetap ada sebagai sumber data mentah, dan
   menaut ke `hr.work.location` (`hr_work_location_id`).

Arah sebaliknya (Odoo → Presenly): **API-nya belum punya endpoint tulis untuk
lokasi**, jadi perubahan lokasi dari Odoo tidak bisa dikirim balik. Yang bisa
dilakukan sementara: melaporkannya sebagai konflik di Sync Log, bukan diam-diam
mengabaikan.

### 2c. Pegawai → `hr.employee`

Yang sudah ada tetap dipakai (dua arah berdasarkan nilai), ditambah penautan yang
belum ada:

- `company_id` dari klien pegawai,
- `work_location_id` dari lokasi kerja pegawai,
- `department_id` dari `bagian` (dibuat bila belum ada),
- dan penulisan lewat `hr.version` yang berlaku aktif.

Pegawai yang tidak punya klien/lokasi tetap disinkronkan tanpa penautan itu, dan
keadaannya dilaporkan — bukan digagalkan.

### 2d. Real-time tanpa cron

| Arah | Pemicu |
| --- | --- |
| Presenly → Odoo | peristiwa webhook: `employee.*` (sudah), ditambah `client.*` dan `work_location.*` |
| Odoo → Presenly | `create`/`write`/`unlink` pada record yang tertaut, dijalankan setelah commit |

Yang harus Anda tahu, dan saya sebutkan karena ini bukan detail kecil:

- **Peristiwa bisa hilang.** Webhook yang gagal dikirim (Odoo mati, jaringan putus)
  tidak dicoba lagi oleh siapa pun kalau tidak ada pemeriksaan berkala. Sistem
  antrean di sisi Presenly sudah menyimpan percobaan dan mengulanginya, tetapi itu
  di sisi pengirim — kalau penerimanya yang tidak pernah menerima, hanya
  rekonsiliasi yang bisa menemukannya.
- **Penghapusan tidak terlihat.** Isyarat perubahan hanya menyebut baris yang masih
  ada. Pegawai atau lokasi yang dihapus di Presenly akan tetap ada di Odoo.
- **Perubahan yang dilakukan di Odoo saat penerima webhook tidak aktif** tidak
  akan pernah terkirim.

Karena itu usulan saya bukan "tanpa cron sama sekali", melainkan **cron sebagai
jaring pengaman yang bisa dimatikan** — persis pola yang sudah dipakai
`presenly_saas` (`Scheduled Refresh`, 0 = mati). Kalau Anda memang ingin
benar-benar tanpa cron, yang menggantikannya adalah tombol **Reconcile** manual
plus laporan konflik; itu jujur, tetapi menuntut disiplin seseorang untuk
menjalankannya.

---

## 3. Yang perlu Anda putuskan

1. **Klien jadi `res.company` (A), `res.partner` (B), atau tetap cermin (C)?**
   Ini menentukan seluruh rancangan di atas. Usulan: A dengan pengaman.
2. **`hr.work.location` boleh diperluas dengan field `presenly_*`?** Tanpa itu,
   geofence tidak punya tempat di Odoo dan radiusnya hanya hidup di cermin.
3. **Cron jaring pengaman: tetap ada (bisa dimatikan), atau benar-benar tanpa cron
   dengan tombol Reconcile?**
4. **Pegawai yang punya beberapa versi (`hr.version`)**: versi mana yang dianggap
   berlaku — yang paling baru mulai, atau yang sedang aktif hari ini?
5. **Perusahaan yang dibuat dari Presenly** ikut serta dalam `check_company` dan
   pemisahan data; apakah pengguna Odoo Anda memang akan berpindah antar
   perusahaan, atau satu orang cukup melihat semuanya?

---

## 4. Fase kerja

| Fase | Isi | Perkiraan |
| --- | --- | --- |
| 1 | Klien → `res.company` (+ setelan, pengaman, laporan) | 1 hari |
| 2 | Lokasi → `res.partner` + `hr.work.location` + perluasan geofence | 1½ hari |
| 3 | Pegawai: tautan `company_id`, `work_location_id`, `department_id` | 1 hari |
| 4 | Webhook: peristiwa `client.*` dan `work_location.*` di kedua repo | 1 hari |
| 5 | Arah Odoo → Presenly untuk lokasi (butuh endpoint tulis baru di API) | 1½ hari |
| 6 | Rekonsiliasi + laporan konflik | ½ hari |

Fase 1–3 bisa dikerjakan tanpa menyentuh sisi Presenly sama sekali (data sudah
tersedia lewat API baca).

---

## 5. Rencana uji

| Yang diuji | Cara |
| --- | --- |
| Perusahaan dibuat sekali | tarik dua kali → jumlah perusahaan tidak bertambah |
| Perusahaan tidak pernah dihapus otomatis | hilangkan dari respons → perusahaan tetap ada, dilaporkan |
| Partner alamat dipakai ulang | dua lokasi satu klien → tidak ada partner kembar |
| Geofence ikut tersalin | bandingkan latitude/radius dengan respons API |
| Pegawai tertaut ke perusahaan & lokasi | periksa `company_id` dan `work_location_id` versi aktif |
| Peristiwa webhook lokasi | kirim payload uji → lokasi diperbarui tanpa cron |
| Perubahan dari Odoo terkirim | ubah nama pegawai di Odoo → panggilan PATCH tercatat |
| Lokasi yang diubah dari Odoo dilaporkan | ubah di Odoo → muncul di Sync Log sebagai belum bisa dikirim |
| Tanda tangan webhook salah | HMAC salah → ditolak, tidak ada yang berubah |

---

## 6. Yang sengaja tidak dikerjakan

- **Menghapus perusahaan atau pegawai dari Odoo** karena hilang di Presenly.
  Penghapusan merusak data akuntansi dan riwayat; yang dilakukan adalah melaporkan.
- **Menebak koordinat atau radius** yang tidak dikirim server.
- **Menyalin `business_sector` ke field native** yang artinya berbeda; disimpan
  sebagai kolom sampingan pada perusahaan.
