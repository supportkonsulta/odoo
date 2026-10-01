# Sinkronisasi pegawai: Odoo `hr.employee` ↔ Presenly `employees`

Status: **dua arah sudah dikerjakan dan terbukti dengan server sungguhan.**

Yang sudah jalan: tarik pegawai, cermin `presenly.saas.employee`, penautan ke
`hr.employee` lewat nopeg, dan penerapan 7 kolom yang ada di kedua sisi. Tombol
**Tarik Pegawai** ada di halaman Langganan.

Arah Odoo → Presenly juga sudah jalan, dikirim **saat disimpan** (setelah
commit), dengan cron harian sebagai jaring pengaman. Arah sebaliknya lewat
webhook, juga dengan tarikan harian sebagai jaring pengaman.

Keputusan yang saya ambil sendiri untuk tujuh pertanyaan di §6, semuanya dipilih
yang paling tidak merusak:

| Pertanyaan | Keputusan | Alasan |
|---|---|---|
| `phone` | `work_phone` | `mobile_phone` ("Work Mobile") dibiarkan, tidak ditulis |
| `address` | `private_street` saja | Odoo memisahkan jalan dan kota; hanya baris jalan yang diisi, sisanya tidak ditebak |
| `bagian` | cermin saja | Membuat `hr.department` otomatis dari teks bebas akan mengotori konfigurasi HR |
| PII | cermin saja | Menambah kolom PII ke model native adalah perubahan skema, bukan keputusan teknis |
| `is_active` | **ditolak** bila pegawai punya akun pengguna Odoo | Menonaktifkan berarti mencabut akses orang tanpa peringatan di Odoo. Keadaannya dilaporkan untuk diputuskan manual |
| Seri waktu sama | Odoo menang | Belum berlaku; baru relevan saat dua arah ada |
| Endpoint tulis | sudah ada (`POST` + `PATCH` di `/v1/employees`) | Dipakai oleh arah balik |

---

## 1. Kenapa harus satu daftar pegawai

Domain `employees` sengaja belum dicerminkan sampai sekarang. Model cermin lain
menyimpan `employee_name` dan `employee_nopeg` sebagai teks, jadi belum ada satu
tempat yang bisa dijadikan acuan pegawai.

Keputusan yang dipilih: **pegawai memakai `hr.employee` native**, bukan cermin
terpisah. Alasannya, kalau Odoo dan Presenly masing-masing punya daftar sendiri,
keduanya akan berbeda dan tidak ada yang bisa dipercaya. Untuk itu modul ini
menambah dependensi `hr`, dan **menolak dipasang bersama `hr_attendance` dan
`hr_holidays`** — absensi dan cuti sudah dicerminkan dari Presenly, jadi keduanya
tidak boleh aktif bersamaan. Lihat README §5c.

---

## 2. Kunci penghubung

`nopeg` adalah satu-satunya penanda yang dimiliki kedua sisi. `hr.employee` tidak
punya kolomnya, jadi perlu field baru:

```
presenly_nopeg = fields.Char(index=True)     # di hr.employee
```

`barcode` (Badge ID) **tidak** dipakai: artinya nomor kartu, bukan nomor
kepegawaian, dan menumpangkan dua arti pada satu kolom akan membingungkan saat
salah satu sisi mengubahnya.

Aturan: `presenly_nopeg` **hanya boleh diisi dari Presenly**. Kalau diubah di
Odoo, barisnya tidak lagi bisa dicocokkan, dan sinkronisasi berikutnya akan
membuat pegawai duplikat.

---

## 3. Pemetaan kolom

### 3a. Ada di kedua sisi — bisa dua arah

| Presenly | `hr.employee` | Catatan |
|---|---|---|
| `name` | `name` | |
| `email` | `work_email` | |
| `phone` | `work_phone` | **perlu diputuskan**: `work_phone` atau `mobile_phone`? |
| `birth_date` | `birthday` | |
| `birth_place` | `place_of_birth` | |
| `address` | `private_street` | **perlu diputuskan**: `address` satu teks bebas, Odoo memisahkan jalan dan kota |
| `is_active` | `active` | **perlu diputuskan**: lihat §4 |

### 3b. Hanya ada di Presenly — tidak punya kolom di Odoo

| Presenly | Usul |
|---|---|
| `nopeg` | `presenly_nopeg` (field baru), hanya baca dari sisi Odoo |
| `bagian` | **perlu diputuskan**: dipetakan ke `department_id` (perlu membuat `hr.department` baru), atau disimpan di cermin saja |
| `role_id` | tidak ada padanan — simpan di cermin |
| `grup` | kolom dari sistem SIK — simpan di cermin |
| `can_approve` | tidak ada padanan — simpan di cermin |
| `no_npwp`, `no_rekening`, `no_bpjs`, `no_bpjs_kes` | PII, tidak ada padanan. **perlu diputuskan**: simpan di cermin saja, atau tambah field di `hr.employee` |

### 3c. Hanya ada di Odoo — tidak dikirim ke Presenly

`job_title`, `job_id`, `parent_id`, `coach_id`, `company_id`,
`resource_calendar_id`, `user_id`, `employee_type`, `km_home_work`, dan 170 kolom
lainnya. Presenly tidak punya kolomnya, jadi tetap milik Odoo dan tidak pernah
disentuh sinkronisasi.

---

## 4. Aturan konflik

Sinkronisasi dua arah harus menjawab: kalau kedua sisi berubah sejak sinkronisasi
terakhir, siapa yang menang?

Usulan: **yang terakhir diubah menang**, dengan syarat masing-masing sisi
mencatat kapan terakhir disinkronkan.

```
presenly_synced_at          = fields.Datetime()   # di hr.employee
presenly_employee_updated_at = fields.Datetime()  # updated_at dari Presenly
```

| Keadaan | Tindakan |
|---|---|
| Hanya Odoo berubah (`write_date > presenly_synced_at`) | kirim Odoo → Presenly |
| Hanya Presenly berubah (`updated_at > presenly_synced_at`) | ambil Presenly → Odoo |
| Keduanya berubah | yang `updated_at`/`write_date`-nya lebih baru menang, **dan konfliknya dicatat** |
| Tidak ada yang berubah | tidak ada panggilan |

Kalau waktunya sama persis, **Odoo menang**, karena pengguna sedang bekerja di
Odoo. Aturan ini harus ditulis di dokumen, bukan dibiarkan tersirat.

Kolom yang dimiliki satu sisi (`nopeg`, PII, `grup`, `can_approve`) tidak pernah
masuk perhitungan konflik.

---

## 5. Endpoint tulis (SUDAH ADA)

Catatan koreksi: dokumen ini sempat menyatakan server belum menerima tulisan
sama sekali. **Itu keliru.** Server sudah punya route tulis pegawai sejak
sebelumnya (`/api/external/employees/upsert`, `/deactivate`, `/disconnect`,
`/change-nopeg`).

Yang ditambahkan adalah padanan v1-nya, karena route warisan menulis **seluruh
objek**: kolom yang tidak dikirim menjadi `null`. Untuk sinkronisasi dua arah itu
berbahaya — Odoo yang hanya mengirim nama dan email akan menghapus `bagian`,
`grup`, dan seluruh PII pegawai itu tanpa pernah menyentuhnya.

| Endpoint | Sifat |
|---|---|
| `POST /api/external/v1/employees` | membuat pegawai baru |
| `PATCH /api/external/v1/employees/{nopeg}` | **hanya** kolom yang dikirim yang ditulis |
| `GET /api/external/v1/employees/writable-fields` | daftar kolom yang boleh ditulis |

Kuncinya `nopeg`, bukan id numerik: nopeg penanda yang dimiliki kedua sisi, jadi
integrasi tidak perlu menyimpan pemetaan id.

Yang **tidak** bisa ditulis dari luar, dan alasannya:

| Kolom | Alasan |
|---|---|
| `nopeg` | kunci penghubung; perubahan nomor punya endpoint sendiri |
| `role_id` | mengubah peran berarti mengubah hak akses |
| `no_npwp`, `no_rekening`, `no_bpjs`, `no_bpjs_kes` | PII |
| `client_id`, `company_id`, `project_id` | sumbernya `employee_placements` |

Mengosongkan kolom harus dikirim sebagai `null` **eksplisit**. Diam bukan berarti
menghapus.

Pegawai yang dibuat lewat endpoint ini mendapat **kata sandi bawaan = nopeg**,
sama seperti route warisan. Keputusan produk: pegawai baru bisa langsung masuk.

Perlu diketahui sebelum diandalkan sebagai pengaman:

- Login memakai nopeg **tidak mewajibkan verifikasi email**. Pemeriksaan
  `is_email_verified` di `AuthService` hanya berlaku bila identifier memuat `@`.
- `nopeg` biasanya berpola dan mudah ditebak (contoh: `iksg-rangga`).
- `role_id` bawaan 3 = `employee`, peran dengan hak paling rendah.

---

## 5a. Kapan tiap arah dijalankan

| Arah | Cara | Alasan |
|---|---|---|
| Odoo → Presenly | trigger `create`/`write` pada `hr.employee`, dijalankan **setelah commit** | perubahan langsung terkirim; transaksi batal tidak mengirim apa pun; jaringan tidak memperlambat penyimpanan |
| Presenly → Odoo | webhook, dengan polling harian sebagai jaring pengaman | server memberi tahu Odoo |

Penanda konteks `presenly_skip_push` dipasang pada setiap penulisan yang
dilakukan sinkronisasi sendiri. Tanpa itu, tarikan akan memicu pengiriman balik
atas nilai yang baru saja diterima, dan berputar tanpa henti.

Cron tetap ada untuk arah tarik, dan sekaligus menjadi jaring pengaman bagi
pengiriman langsung yang gagal.

---

## 5b. Aturan konflik yang benar-benar dipakai

Rancangan awal di §4 memakai perbandingan jam (`updated_at` vs `write_date`).
**Itu tidak dikerjakan**, karena jam dua server tidak bisa dibandingkan dengan
andal, dan `updated_at` bisa saja tidak berubah walaupun isinya berubah.

Yang dipakai: **perbandingan nilai terhadap snapshot**.

`hr.employee.presenly_synced_values` menyimpan keenam kolom bersama sebagaimana
adanya saat sinkronisasi terakhir. Setiap sinkronisasi membandingkan nilai
sekarang di kedua sisi terhadap snapshot itu:

| Odoo vs snapshot | Presenly vs snapshot | Tindakan |
|---|---|---|
| sama | sama | tidak ada |
| beda | sama | kirim Odoo → Presenly |
| sama | beda | terapkan Presenly → Odoo |
| beda | beda | **bentrok**: Presenly menang, dilaporkan |

Tidak ada jam yang dibandingkan, jadi tidak ada zona waktu maupun selisih waktu
server yang bisa membuat kesimpulan salah.

---

## 6. Yang harus diputuskan lebih dulu (SUDAH DIJAWAB)

Ketujuhnya sudah dijawab; jawabannya ada di tabel ringkasan di awal dokumen ini.
Tujuh pertanyaan di bawah disimpan sebagai riwayat, dan supaya jelas **apa** yang
pernah harus diputuskan. Urutan pengerjaan di bagian bawah juga sudah selesai
seluruhnya.

1. `phone` → `work_phone` atau `mobile_phone`?
2. `address` (satu teks) → `private_street` saja, atau dipecah ke jalan + kota?
3. `bagian` → `hr.department` (dibuat otomatis), atau disimpan di cermin?
4. PII (`npwp`, `rekening`, `bpjs`) → field baru di `hr.employee`, atau cermin saja?
5. `is_active` → siapa yang berhak menonaktifkan pegawai, Odoo atau Presenly?
6. Siapa yang menang kalau waktunya sama persis?
7. Apakah endpoint tulis di sisi server akan dibuat? Kalau ya, kapan?

Urutan pengerjaan yang dulu direncanakan, ketiganya sudah dikerjakan:

1. Field `presenly_nopeg` + pencocokan pegawai (Presenly → Odoo). ✅
2. Cermin `presenly.saas.employee` untuk kolom yang tidak punya rumah di Odoo. ✅
3. Sinkronisasi dua arah. ✅

## 7. Cabang, dan akses perusahaan pengguna (diputuskan 2026-09-28)

Empat pertanyaan, dan jawaban pemiliknya:

| Pertanyaan | Jawaban |
| --- | --- |
| Boleh penempatan memberi akses perusahaan Odoo ke pengguna itu? | Ya, terbatas pada perusahaan hasil cermin klien |
| Perusahaan bawaan pengguna ikut pindah ke cabangnya? | Tidak; perpindahan hanya lewat pemilih perusahaan |
| Akses dicabut saat penempatan berakhir? | **Tidak**, supaya tidak ada kejutan berupa hilangnya perusahaan di tengah pekerjaan |
| Perlu tabel cermin penempatan? | Tidak untuk sekarang; cukup daftar cabang di pegawai |

Akibat yang perlu diketahui:

- Sinkronisasi **hanya menambah** akses. Kalau seseorang menghapusnya di Odoo,
  tarikan berikutnya menambahkannya kembali. Itu konsekuensi langsung dari
  jawaban ketiga, bukan kelalaian.
- Daftar cabang (`hr.employee.presenly_client_ids`) tetap keadaan sekarang,
  sedangkan aksesnya menumpuk. Keduanya bisa berbeda, dan itu memang disengaja.
- Riwayat penempatan tidak disimpan, jadi pertanyaan "dulu di cabang mana, dari
  kapan sampai kapan" belum bisa dijawab. Tabel cermin penempatan adalah
  pekerjaan lanjutan bila itu dibutuhkan.
- Peristiwa `placement.*` belum ada di sisi SaaS. Perubahan penempatan sekarang
  sampai lewat peristiwa pegawai, `sync.changed` dengan `dataset=placements`
  (klien sudah mengenalinya), atau cron.
