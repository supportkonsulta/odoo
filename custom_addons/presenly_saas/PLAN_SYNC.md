# Plan: kesegaran sinkronisasi pengajuan

Status: **Fase A, B, dan C sudah dikerjakan** (19.0.1.9.0 – 19.0.1.12.0).
Fase D belum, dan memang menunggu keputusan.

**Urutan yang berubah setelah dipakai:** pemicu dari halaman menjadi jalan utama,
dan **ambang waktunya dibuang sama sekali**. Setiap kali halaman cermin dibuka
(hanya halaman pertama), satu permintaan murah ke `GET /v1/presenly/changes`
menjawab jenis mana yang berubah; hanya itu yang ditarik. Dengan begitu "periksa
setiap kali dibuka" berbiaya satu permintaan kecil, bukan tujuh penarikan.

Cron menjadi jaring pengaman yang bisa dimatikan lewat Settings (**Scheduled
Refresh**, 0 = mati), dan tombolnya tinggal untuk penarikan pertama yang
terpotong batas 10 halaman. Catatan penting: cron juga satu-satunya yang
menangkap penghapusan di sisi server, karena pemeriksaan perubahan hanya melihat
baris yang masih ada.

**Perluasan setelah dipakai:** pemicu dari halaman semula hanya mencakup lima
jenis pengajuan, dan itu terbukti kurang — absensi yang baru di-tap dari aplikasi
tidak muncul. Sekarang cakupannya seluruh cermin, dan lihat
§"Perbandingan lengkap" untuk hasil pengukurannya.
Konteks: pengguna menambahkan pengajuan baru di Presenly, dan pengajuannya tidak
muncul di Odoo.

---

## 0. Ringkasan

Pengajuan baru tidak muncul karena **sinkronisasinya hanya ditarik sekali sehari,
dan tidak ada satu pun cara menariknya sendiri dari Odoo**. Bukan karena datanya
salah, dan bukan karena pemetaannya gagal.

Cara memperbaikinya **tidak harus lewat tombol**. Yang paling cocok untuk kasus
ini justru pemicu otomatis saat halamannya dibuka: pengguna tidak perlu tahu ada
sinkronisasi, dan yang ia lihat adalah data pada saat ia melihatnya. Tombol tetap
disiapkan, tetapi pekerjaannya berbeda — melengkapi bulan lama, dan mencoba ulang
setelah gagal. Itu dua hal yang tidak bisa dilakukan pemicu otomatis.

Tiga hal yang ditemukan:

1. **Wizard penarikan tidak bisa dibuka siapa pun.** Modelnya
   (`presenly.saas.pull.wizard`) punya form, tetapi tidak ada `act_window`, tidak
   ada entri menu, dan tidak ada tombol yang membukanya. Bantuan di layar
   menyuruh pengguna "Run **Pull Period Data**" — perintah yang tidak ada di
   antarmuka. Satu-satunya tombol manual yang ada adalah **Refresh Reference**,
   dan itu hanya menyegarkan cermin referensi — **bukan pengajuan**.
2. **Cron penarikan berjalan harian**, jadi pengajuan baru menunggu sampai
   ~24 jam sebelum terlihat.
3. **Saringannya memakai tanggal bisnis, bukan waktu perubahan.** Penarikan
   mengirim `since`/`until`, dan API memetakannya ke kolom tanggal masing-masing
   jenis (`leave_date`, `overtime_date`, `certificate_date`, `date`,
   `requester_date`). Akibatnya pengajuan yang tanggalnya di luar rentang tidak
   pernah ikut tertarik, kapan pun ia dibuat:

   | Jenis | Kolom tanggal | Contoh yang terlewat |
   | --- | --- | --- |
   | Koreksi presensi | `date` (tanggal presensinya) | koreksi untuk presensi bulan lalu |
   | Tukar shift | `requester_date` (tanggal shift-nya) | tukar shift untuk bulan depan |
   | Cuti | `leave_date` | cuti yang diajukan untuk bulan depan |
   | Surat dokter | `certificate_date` | surat yang diisi tanggal mundur |
   | Lembur | `overtime_date` | lembur yang dicatat mundur |

   Padahal API-nya **sudah** menyediakan `updated_since` (menyaring
   `updated_at`), dan modul ini belum memakainya sama sekali.

---

## 1. Bukti

Dari tenant `iksg`, saat pengajuan baru tidak muncul:

```
employee_leaves                  2 baris | terbaru: 2026-09-23 01:55:42
doctor_certificates              2 baris | terbaru: 2026-09-23 01:52:50

Odoo: presenly.saas.leave                 1 baris  (CT-2609-1204)
Odoo: presenly.saas.medical.certificate   0 baris

Presenly SaaS: Pull Period Data  | days | nextcall=2026-09-23 04:32:25
```

Dibuat 01:52–01:55, cron berikutnya 04:32. Datanya memang belum tertarik.

Bukti saringan tanggal di kode:

```python
# models/presenly_saas_config.py (dalam _pull_period_datasets)
params = {
    'since': fields.Date.to_string(first_day),
    'until': fields.Date.to_string(last_day),
    'limit': 500,
}
```

Bukti filter yang tersedia di API (`ExternalRawDataService._buildWhere`):

```js
if (query.updated_since !== undefined && query.updated_since !== '') {
    and.push({ updated_at: { [Op.gt]: since } });   // ← belum dipakai modul
}
if (cfg.dateField && (query.since || query.until)) {
    where[cfg.dateField] = range;                    // ← yang dipakai modul
}
```

---

## 2. Peta sinkronisasi yang berlaku sekarang

| Pemicu | Jadwal | Cakupan | Dipakai pengguna? |
| --- | --- | --- | --- |
| Cron `Pull Period Data` | harian | presensi + rekap + 5 pengajuan + timesheet, 2 bulan terakhir | tidak (otomatis) |
| Cron `Refresh Subscription` | harian | langganan | tidak |
| Cron `Clean Up Mirrored Data` | mingguan | pemangkasan cermin | tidak |
| Cron `Sync Employees` (bridge) | harian | pegawai | tidak |
| Tombol **Refresh Reference** | manual | referensi saja | ya — **bukan pengajuan** |
| Wizard **Pull Period Data** | — | presensi + pengajuan + timesheet | **tidak ada pintunya** |
| Webhook | seketika | **pegawai saja** | otomatis |

Untuk pengajuan: **harian, dan hanya itu.**

---

## 3. Kenapa bukan tombol sebagai jalan utama

Tombol menuntut pengguna tahu bahwa ada yang perlu ditarik, dan ia harus
menekannya sebelum datanya benar. Empat pertanyaan yang muncul karenanya:

- Kapan ia harus menekan? Sebelum membuka daftar? Sesudah melihat datanya salah?
- Kalau ada dua orang melihat daftar yang sama, siapa yang menekan?
- Kalau ia lupa menekan, apakah datanya salah? Menurut layarnya, ya.
- Kalau penarikan gagal, apa yang harus ia lakukan berikutnya?

Pemicu otomatis menjawab keempatnya dengan tidak memunculkan pertanyaannya. Dan
Odoo menyediakan bagian-bagian yang dibutuhkan:

| Kebutuhan | Yang tersedia di Odoo |
| --- | --- |
| Menyegarkan saat halaman dibuka | `web_search_read` bisa ditimpa di model cermin |
| Supaya TIDAK nge-blok halaman | `ir.cron._trigger()` — menjadwalkan cron berjalan segera, di luar permintaan pengguna |
| Supaya N pengguna tidak memicu N penarikan | `SELECT ... FOR UPDATE` pada baris konfigurasi (pola yang dipakai core) |
| Supaya daftar menyegarkan diri setelah datanya tiba | `bus.bus._sendone()` — memberi tahu klien |

Harga yang harus dibayar, dan disebut apa adanya:

- **Membuka daftar menjadi perbuatan yang menulis.** Penarikan berjalan dengan
  `sudo`, jadi pengguna yang hanya boleh membaca tetap bisa memicunya. Ini
  disengaja — cerminnya memang bukan milik pengguna — tetapi harus tercatat.
- **Kegagalan penarikan tidak boleh muncul di halaman pengguna.** Penarikan yang
  dipicu dari halaman harus tetap mengembalikan kegagalan sebagai nilai, dan
  halamannya menampilkan cermin apa adanya. Kalau tidak, satu gangguan di server
  Presenly membuat daftar pengajuan tidak bisa dibuka.
- **Panggilan API bertambah.** Tiap penyegaran berarti 5 panggilan (satu per jenis
  pengajuan) ditambah halamannya. Dengan `updated_since` isinya biasanya kosong,
  tetapi batas laju tenant tetap perlu dihormati — karena itu ada penjagaan waktu.

---

## 4. Rencana

Urutannya sengaja: A adalah fondasinya. Tanpa penarikan tambahan yang murah,
pemicu otomatis berarti menarik ulang seluruh rentang setiap kali ada yang
membuka halaman.

### Fase A — penarikan tambahan untuk pengajuan (fondasi) — **selesai**

1. **Mode tambah-perbarui (`upsert`) di mixin cermin.** `_mirror_replace_range`
   hari ini menghapus rentang lalu membuat ulang; penarikan tambahan tidak boleh
   menghapus apa pun. Tambahan `_mirror_upsert(company, rows)`: perbarui baris
   yang `external_id`-nya sudah ada, buat yang belum.
2. **Penanda waktu per jenis pengajuan**, bukan satu untuk semuanya: satu jenis
   yang gagal tidak boleh menaikkan penanda jenis lain.
3. **Penarikan tambahan per jenis** dengan `updated_since = penanda − tumpang
   tindih`. Tumpang tindih beberapa menit dipakai sengaja: `updated_since`
   memakai `>` sehingga baris yang berubah pada detik yang sama bisa terlewat.
   Hanya lima jenis pengajuan; presensi, rekap, dan timesheet tidak ikut.
4. **Cron `Presenly SaaS: Sync Requests` tiap 15 menit.** Ini juga yang menjadi
   landasan pemicu otomatis di Fase B, dan tetap berguna tanpa Fase B.
5. **Penarikan rentang harian tetap dipertahankan** sebagai rekonsiliasi: ia yang
   menangkap penghapusan di sisi server dan melengkapi baris yang terlewat.

Berkas: `models/presenly_saas_mirror_mixin.py`, `models/presenly_saas_config.py`,
`data/ir_cron_data.xml`, `tests/`.

### Fase B — pemicu otomatis saat halaman dibuka — **selesai**

1. **Satu penimpaan di `presenly.saas.submission.mixin`** mencakup kelima jenis:
   pada `web_search_read`, periksa apakah cermin sudah tua.
2. **Kalau tua, jalankan penarikan tambahan.** Dua pilihan, dan bedanya hanya di
   kapan datanya terlihat:

   | Pilihan | Yang pengguna alami | Harga |
   | --- | --- | --- |
   | **Menunggu (inline)** — tarik sebelum data daftar dikembalikan | daftar **sudah berisi** pengajuan baru saat halaman terbuka; jeda ~1 detik karena dengan `updated_since` isinya biasanya kosong | membuka daftar jadi menunggu jaringan; perlu timeout pendek dan penjagaan waktu |
   | **Menitipkan ke cron** — `_trigger()` lalu beri tahu lewat bus | halaman terbuka seketika; daftar menyegarkan diri 1–3 detik kemudian | perlu bus + penanganan di sisi klien |

   **Usulan: pilihan pertama sebagai bawaan**, karena langsung menjawab keluhan
   "tidak langsung tampil" tanpa bagian bergerak tambahan, dengan timeout pendek
   (bawaan 10 detik terlalu lama untuk halaman daftar — pakai ~3 detik) dan
   kegagalan yang tidak pernah menggagalkan halaman. Pilihan kedua disiapkan
   sebagai jalan peningkatan kalau jeda itu ternyata mengganggu.

3. **Penjagaan waktu (throttle)** per perusahaan: paling sering sekali per N
   menit, dengan `SELECT ... FOR UPDATE` pada baris konfigurasi supaya dua
   pengguna yang membuka bersamaan tidak menarik dua kali.
4. **Batasi cakupannya**: hanya kelima model pengajuan, hanya pada pembacaan
   daftar. Pivot, grafik, dan laporan tidak memicu apa pun.

Berkas: `models/presenly_saas_submission_mirrors.py` (atau mixin-nya),
`models/presenly_saas_config.py`, `tests/`.

### Fase C — tombol untuk yang tidak bisa otomatis — **selesai**

Pemicu otomatis hanya mengambil **perubahan terbaru**; ia tidak bisa melengkapi
bulan lama, dan tidak bisa mencoba ulang setelah gagal berulang. Karena itu
wizard yang sudah ada tetap dibuka:

1. `ir.actions.act_window` untuk `presenly.saas.pull.wizard`.
2. Tombol **Pull Period Data** di form Subscription (group manajer), di samping
   Refresh Reference.
3. Bantuan di layar yang menyebut "Run **Pull Period Data**" agar menunjuk ke
   tombol yang benar-benar ada.

Pekerjaannya jelas: memilih bulan, menarik ulang setelah gagal, dan menelusuri
data yang tidak sesuai dugaan.

### Fase D — seketika lewat webhook (opsional, menyentuh dua repo)

Kendala lebih dulu: **pendaftaran webhook di server hanya menyimpan satu alamat
per tenant**, sedangkan penerimanya sekarang duduk di modul bridge dan hanya
mengurus pegawai. Kalau modul inti memasang penerimanya sendiri, keduanya saling
menimpa. Jadi penerimanya harus satu, dimiliki modul inti, dan modul bridge
menambahkan penangan untuk peristiwanya.

1. **Backend:** hook pada lima model pengajuan (pola `employeeWebhookHook.js`),
   nama peristiwa per jenis. Isi payload tetap **isyarat saja** — tanpa PII.
2. **Inti:** pindahkan penerima webhook ke `presenly_saas`, sediakan titik sambung
   penangan per peristiwa, pindahkan penangan pegawai ke modul bridge.
3. **Inti:** peristiwa pengajuan menjadi pemicu penarikan tambahan — bukan
   mengambil satu baris. Saringan `id` tidak tersedia di API: `?id=2` diabaikan
   diam-diam dan justru mengembalikan baris lain.
4. Verifikasi HMAC tetap; peristiwa yang tidak dikenal dijawab 200 tanpa diproses.

### Yang berbeda dari rencana, dan alasannya

1. **Penjagaan waktu tidak disimpan di kolom konfigurasi.** Rencananya memakai
   kolom `last_request_sync_at`. Itu membuat penyegaran menulis ke baris
   konfigurasi dari transaksi tersendiri, dan transaksi tersendiri akan menunggu
   kunci baris itu bila transaksi pemanggil sedang memegangnya — halaman tidak
   boleh menunggu kunci. Penjagaan waktunya sekarang dibaca dari **log
   sinkronisasi**: percobaan yang gagal pun tercatat, sehingga server yang sedang
   mati tidak dicoba ulang oleh setiap halaman yang dibuka, tanpa menulis apa pun
   ke konfigurasi.
2. **Penjagaan waktunya memakai kunci penasihat (advisory lock) per perusahaan**,
   dan yang "try": kalau ada penarikan yang sedang berjalan, pemanggil berikutnya
   langsung menyerah alih-alih menunggu.
3. **Penyegaran berjalan di transaksi tersendiri.** Bukan pilihan gaya:
   `web_search_read` ditandai `@api.readonly`, sehingga cursornya bisa hanya-baca
   dan tulisan dari sana ditolak PostgreSQL. Cursor Odoo me-rollback saat keluar,
   jadi transaksi itu di-commit sendiri.
   Konsekuensinya untuk pengujian: transaksi tersendiri tidak bisa melihat data
   yang belum di-commit milik tes, sehingga logikanya diuji langsung dan
   sambungannya diuji dengan tiruan. Bukti ujung-ke-ujungnya diambil dari browser
   terhadap server sebenarnya.

### Perbandingan lengkap (23 Sep 2026, setelah perluasan)

Seluruh empat belas dataset dibandingkan langsung dengan API-nya:

```
work-locations 2=2  shifts 2=2  attendance-modes 2=2  holidays 0=0
work-day-setups 2=2  projects 0=0  leaves 2=2  overtimes 3=3
medical-certificates 2=2  attendance-corrections 0=0  shift-swaps 0=0
timesheets 0=0  attendance-sessions 3=3  attendance-recap 1=1

KESIMPULAN: semua sinkron
```

Presensi `2026-09-23` (status `open`) — absensi yang di-tap dari aplikasi dan
sebelumnya tidak pernah muncul — masuk lewat pembukaan daftar **Presensi**, dan
satu kali penarikan itu ikut menarik timesheet, log presensi, rekap, dan keenam
cermin referensi.

### Bukti ujung-ke-ujung (23 Sep 2026)

Pengajuan yang dibuat pukul 01:52–01:55 di sisi Presenly belum tercermin di Odoo.
Daftar **Requests → Leave** dibuka pukul 02:15, dan:

```
cuti tercermin sebelum dibuka : 1   (CT-2609-1204)
cuti tercermin sesudah dibuka : 2   (CT-2609-5864 ikut masuk)
surat dokter                  : 0 → 2

log pada detik yang sama      : leaves, overtimes, medical-certificates,
                                attendance-corrections, shift-swaps  (5 panggilan)
log presensi/timesheet        : tidak ada
penanda waktu per jenis       : terisi untuk kelima jenis

daftar dibuka lagi 1 menit kemudian: tidak ada panggilan baru (penjagaan waktu)
```

---

## 5. Yang perlu Anda putuskan

1. **Menunggu (~1 detik) atau menitipkan ke cron?** Usulan: menunggu, dengan
   timeout 3 detik.
2. **Seberapa tua cermin boleh sebelum disegarkan otomatis?** Mis. 5 menit
   (bawaan usulan) atau 15 menit — ini juga yang menentukan berapa sering API
   tenant dipanggil saat halaman dibuka berkali-kali.
3. **Fase D dikerjakan atau tidak.** Fase A–C sudah membuat pengajuan muncul
   saat halaman dibuka. Webhook membuatnya muncul tanpa perlu dibuka.
4. **Irama cron `Sync Requests`:** 15 menit, 5 menit, atau 30 menit.

---

## 6. Rencana uji

| Yang diuji | Cara |
| --- | --- |
| Tambahan tidak menghapus | baris di luar rentang tetap ada setelah penarikan tambahan |
| Tidak ada duplikat | jalankan dua kali; constraint `(company_id, external_id)` tidak dilanggar |
| Pengajuan bertanggal lama ikut tertarik | baris `leave_date` bulan lalu dengan `updated_at` sekarang |
| Penanda tidak naik saat gagal | siram panggilan gagal, periksa penandanya |
| Pemicu otomatis tidak menggagalkan halaman | API dimatikan, buka daftar, halaman tetap terbuka dan menampilkan cermin |
| Penjagaan waktu bekerja | dua pembacaan berturut-turut hanya memicu satu penarikan |
| Presensi tidak ikut tersentuh | hitung panggilan di sync log selama satu jam |
| Kelima jenis terpicu | buka kelima daftarnya, periksa sync log |
| Modul bridge tidak regresi | seluruh suite `presenly_saas` + `presenly_saas_hr` |

---

## 7. Yang sengaja tidak dikerjakan

- **Menarik presensi tiap 15 menit.** Tabelnya besar dan penarikan rentang
  menulis ulang seluruh rentangnya. Yang butuh segar adalah pengajuan.
- **Menyaring satu baris lewat `id`.** API belum mendukungnya, dan mengabaikan
  parameter yang tidak dikenal tanpa pemberitahuan adalah jebakan tersendiri.
- **Menampilkan data yang belum ditarik.** Cermin hanya bisa menampilkan apa yang
  sudah sampai. Yang bisa dilakukan adalah memperkecil jeda, bukan menghapusnya.
