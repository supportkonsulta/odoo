# Plan: Fitur Absensi & Monitoring di Odoo

Rencana penerapan seluruh fitur absensi dan monitoring Presenly ke aplikasi Odoo
`presenly_saas`, langkah demi langkah.

**Status:** draft — belum dieksekusi di luar Fase 1
**Modul:** `custom_addons/presenly_saas`
**Tenant uji:** `iksg` (satu-satunya tenant dengan data presensi)

---

## 1. Tujuan

Menjadikan aplikasi Presenly SaaS di Odoo bisa dipakai untuk **melihat,
menyaring, dan mengekspor** data absensi dan monitoring dari server Presenly,
tanpa menyentuh model native Odoo (`hr.attendance` dan sejenisnya).

Bukan tujuan: menggantikan Presenly SaaS, atau memindahkan sumber kebenaran ke
Odoo.

---

## 2. Fakta lapangan (hasil pemeriksaan, bukan asumsi)

Ada **tiga lapisan** API, dan hanya sebagian yang tersedia sekarang.

### 2.1 `/v1/presenly/*` — bentuk bisnis (paling nyaman untuk Odoo)

| Endpoint | Status | Dipakai |
|---|---|---|
| `attendance-logs` | ✅ tersedia | **sudah** (Fase 1) |
| `attendance-recap` | ✅ tersedia | **sudah** (Fase 1) |
| `leaves`, `overtimes`, `corrections`, `shift-swaps`, `timesheets` | ⏳ direncanakan | belum bisa |
| `schedules`, `placements`, `medical`, `sppd`, `dashboard` | ⏳ direncanakan | belum bisa |

Katalog ini bisa dibaca sendiri dari Odoo lewat menu **Fitur Presenly**.

### 2.2 `/v1/{resource}` — data per sumber daya, **26 tersedia sekarang**

Bentuk yang disarankan: `GET /v1/{resource}`, mis. `/v1/employees`,
`/v1/attendance-sessions`, `/v1/work-locations`. Relasi dikirim sebagai objek
bersarang (`employee`, `location`, `shift`), bukan kunci asing mentah, sehingga
Odoo tidak perlu join sendiri dan tidak bergantung pada skema database.

`/v1/raw/{domain}` masih berlaku sebagai bentuk warisan. Jangan dipakai untuk
pekerjaan baru.

**26 resource tersedia sekarang:**

`employees`, `placements`, `work-locations`, `shifts`, `attendance-sessions`,
`overtimes`, `overtime-attendances`, `leaves`, `leave-types`, `projects`,
`contracts`, `internal-companies`, `attendance-modes`, `holidays`,
`work-day-setups`, `timesheets`, `medical-certificates`,
`attendance-corrections`, `leave-quotas`, `weekly-schedules`,
`weekly-schedule-segments`, `daily-schedules`, `schedule-segments`,
`user-shift-schedules`, `shift-swaps`, `personal-profiles`

Ini penting: **sebagian besar pekerjaan bisa dimulai sekarang** tanpa menunggu
server, karena lapisan raw sudah lengkap.

### 2.3 Monitoring

**Tidak ada endpoint monitoring eksternal.** Yang ada hanya internal ber-JWT:
`/api/monitoring/attendance`, `/api/monitoring/timesheets`,
`/api/monitoring/projects`.

Konsekuensi: monitoring di Odoo harus **dirakit lokal** dari data yang sudah
ditarik, atau menunggu endpoint baru di server.

---

## 3. Keputusan yang harus diambil lebih dulu

| # | Pertanyaan | Pilihan | Usulan |
|---|---|---|---|
| 1 | Arah data | (a) baca saja, (b) baca + tulis (approve dari Odoo) | **a dulu**. Menulis berarti Odoo mengubah data operasional di SaaS, dan itu butuh endpoint aksi + keputusan siapa berwenang |
| 2 | Sumber untuk data yang business-endpoint-nya belum ada | (a) pakai `/v1/{resource}` sekarang, (b) tunggu `/v1/presenly/*` | **a**, karena resource sudah tersedia dan bentuknya sudah bersarang; b bisa menyusul tanpa membuang pekerjaan |
| 3 | Cakupan arsip | (a) jendela bergulir (mis. 12 bulan), (b) arsip penuh | **a**, agar tabel Odoo tidak tumbuh tanpa batas |
| 4 | Monitoring dihitung di mana | (a) agregat lokal dari cermin, (b) tunggu endpoint dashboard | **a**, supaya bisa dikerjakan sekarang tanpa menunggu server |
| 5 | Berapa domain raw yang benar-benar ditarik | semua 26, atau hanya yang dipakai | **hanya yang dipakai**, satu per fase |

---

## 4. Fase, langkah demi langkah

### Fase 0 — Persiapan (0,5 hari)

**Sudah sebagian dikerjakan.**

1. Kunci API tenant `iksg` sudah dibuat: `psk_b2af7a41…` (label "Odoo testing
   iksg"), dan sudah diuji: `/v1/subscription`, `/v1/presenly/features`,
   `/v1/presenly/attendance-logs` semua 200; header tenant lain → 403.
2. Isi konfigurasi koneksi di Odoo dengan kunci itu.
3. Pastikan menu **Fitur Presenly** menarik 11 fitur (2 tersedia, 9 direncanakan).

**Deliverable:** koneksi Odoo ↔ SaaS hidup untuk tenant `iksg`.

---

### Fase 1 — Absensi inti (SUDAH DIKERJAKAN)

Log presensi dan rekap, cermin per periode.

| Sudah ada | Keterangan |
|---|---|
| Model `presenly.saas.attendance.log` + `recap` | cermin, diganti per periode |
| Menu **Data Presensi** dan **Rekap Presensi** | list view dengan filter & ekspor bawaan Odoo |
| Wizard **Tarik Data Presensi** | pilih bulan + tahun |
| Batas 10 halaman + pemberitahuan terpotong | supaya cermin tak lengkap terlihat tak lengkap |

**Yang perlu ditambahkan di fase ini (0,5 hari):**
1. Uji ulang khusus dengan `iksg` (sebelumnya sudah, tapi pakai key global).
2. Tambahkan tombol **Tarik** di header list view, supaya bisa dari halaman data,
   tidak hanya dari wizard.

---

### Fase 2 — Master data pendukung absensi (1 hari)

Tujuan: data presensi punya konteks lengkap, tanpa merakit manual.

1. Model cermin generik **`presenly.saas.raw.record`**: satu model untuk domain
   ringan, dengan `domain`, `external_id`, `payload` (Json), `fetched_at`.
   Alasannya: membuat 26 model khusus untuk data yang jarang dibaca adalah
   pemborosan; data ringan cukup disimpan sebagai payload dan ditampilkan
   lewat field yang di-*compute* saat dibutuhkan.
2. Tarik resource prioritas: `/v1/work-locations`, `/v1/shifts`,
   `/v1/attendance-modes`, `/v1/holidays`, `/v1/work-day-setups`.
   Bentuknya sudah bersarang, jadi tidak ada join manual di sisi Odoo.
3. Menu **Referensi** berisi lima daftar itu, masing-masing dengan filter.
4. Uji: bandingkan jumlah baris di Odoo dengan `meta`/jumlah di server.

**Kenapa generik:** kalau nanti salah satu domain perlu kolom khusus (mis.
`work-locations` butuh peta), model itu bisa dinaikkan menjadi model sendiri
tanpa mengubah yang lain.

---

### Fase 3 — Monitoring presensi (1,5 hari)

Karena server belum punya endpoint monitoring, agregat dihitung **lokal** dari
cermin yang sudah ada.

1. Model `presenly.saas.monitoring.snapshot` (TransientModel cukup) yang
   menghitung dari cermin: kehadiran per pegawai, per lokasi, per status,
   terlambat, alpha.
2. View pivot + graph bawaan Odoo (tidak perlu menulis grafik sendiri).
3. Filter periode memakai `work_date` yang sudah ada di cermin.
4. Menu **Monitoring Presensi**.
5. Uji silang: angka agregat lokal harus **sama** dengan
   `/v1/presenly/attendance-recap` untuk periode yang sama. Kalau berbeda, itu
   tanda cermin tidak lengkap.

**Ini satu-satunya fase yang memerlukan tarikan lebih panjang dari satu bulan**,
jadi rolling window dari Keputusan 3 mulai berlaku di sini.

---

### Fase 4 — Pengajuan: cuti, lembur, izin, koreksi, tukar shift (2–3 hari)

Dua pilihan, dan keduanya sah:

**Jalur A (bisa sekarang)** — tarik lewat `/v1/{resource}`:
`leaves`, `overtimes`, `medical-certificates`, `attendance-corrections`,
`shift-swaps`. Bentuknya kolom DB, jadi sebagian relasi harus diterjemahkan
sendiri (mis. `user_id` → nama pegawai dari domain `employees`).

**Jalur B (lebih rapi, perlu server)** — tunggu `/v1/presenly/leaves` dan
kawan-kawan, yang sudah mengirim bentuk bisnis beserta relasinya.

**Usulan: Jalur A dulu**, dan struktur model dibuat sama seperti yang nanti
dikirim Jalur B, supaya saat endpoint bisnis tersedia, penarikan tinggal
diarahkan ulang tanpa mengubah view.

1. Cermin untuk lima jenis pengajuan, dengan status dan pemohon.
2. Menu **Pengajuan** dengan submenu per jenis.
3. Filter: menunggu persetujuan, disetujui, ditolak, per periode.
4. **Belum ada aksi setujui/tolak** — itu Keputusan 1, dan sengaja ditahan.

---

### Fase 5 — Timesheet & proyek (1 hari)

1. Resource: `/v1/timesheets`, `/v1/projects`, `/v1/placements`.
2. Model cermin timesheet, menu **Timesheet**, filter per proyek dan periode.
3. Monitoring timesheet menyusul di fase yang sama bila waktunya cukup.

---

### Fase 6 — Penutup & operasional (1 hari)

1. **Cron penarikan harian** untuk data yang berubah sering (log presensi),
   terpisah dari cron langganan yang sudah ada.
2. **Pembersihan rolling window**: hapus cermin lebih tua dari N bulan, dengan
   N dari konfigurasi.
3. **Ekspor** memakai ekspor bawaan Odoo — tidak ada yang perlu ditulis.
4. **README**: daftar endpoint yang dikonsumsi, arti setiap menu, dan batas
   yang dipegang.
5. **Terjemahan**: regenerasi `id.po` (pola yang sudah dipakai, saat ini 286/286).
6. **Uji keseluruhan** dengan `iksg`.

---

## 5. Ringkasan estimasi

| Fase | Isi | Perlu ubah server? | Estimasi |
|---|---|---|---|
| 0 | Persiapan & kunci iksg | tidak | 0,5 hari |
| 1 | Absensi inti (sudah dikerjakan) | tidak | 0,5 hari |
| 2 | Master data pendukung | tidak | 1 hari |
| 3 | Monitoring presensi | tidak | 1,5 hari |
| 4 | Pengajuan (cuti/lembur/izin/koreksi/tukar shift) | tidak, lewat raw | 2–3 hari |
| 5 | Timesheet & proyek | tidak | 1 hari |
| 6 | Operasional & penutup | tidak | 1 hari |
| | **Total** | | **7,5–8,5 hari** |

**Semua fase bisa dikerjakan tanpa mengubah server**, karena lapisan raw sudah
lengkap. Endpoint `/v1/presenly/*` yang masih `planned` hanya akan membuat
bentuk datanya lebih rapi, bukan membuka kemampuan baru.

---

## 6. Risiko

| Risiko | Mitigasi |
|---|---|
| Cermin tidak lengkap tapi tampak lengkap | Batas halaman dibandingkan dengan `meta.total`, dan selisihnya diberitahukan (sudah jalan di Fase 1) |
| Tabel Odoo tumbuh tanpa batas | Rolling window (Keputusan 3) + cron pembersihan (Fase 6) |
| Data mentah sulit dibaca pengguna | Fase 2 memakai model generik; hanya domain yang benar-benar dipakai yang ditarik |
| Agregat lokal berbeda dari server | Uji silang wajib di Fase 3 terhadap `attendance-recap` |
| Penarikan panjang mengunci worker | Batas halaman, `limit` per halaman, dan timeout yang sudah ada |

---

## 7. Verifikasi yang dipegang setiap fase

1. Tarik dengan tenant `iksg`, bandingkan jumlah baris dengan yang dilaporkan
   server (`meta.total`).
2. Tarik ulang periode yang sama → jumlah baris **tidak bertambah** (cermin
   diganti, bukan ditumpuk).
3. Matikan koneksi atau pakai kunci salah → muncul notifikasi gagal **dan** satu
   baris gagal di **Sync Log**.
4. Ganti bahasa user ke `id_ID` → label menu dan field berbahasa Indonesia.
5. `odoo-bin --test-enable --test-tags=/presenly_saas` → seluruh tes hijau.
