# Plan: lampiran pengajuan & penyederhanaan bagian Persetujuan

Status: rencana, belum dikerjakan.
Permintaan: (1) setiap pengajuan yang melampirkan file harus bisa dilihat langsung
lewat komponen native Odoo, tampil di sisi kanan; (2) bagian Persetujuan cukup
menampilkan rangkaian langkahnya saja, keterangan lainnya dihapus.

---

## 0. Ringkasan

Dua pekerjaan yang tidak berhubungan, dan yang pertama jauh lebih besar daripada
kedengarannya: file unggahan Presenly **tidak bisa diambil** lewat API, dan
tampilan lampiran native Odoo (panel kanan) datang dari modul `mail`, bukan dari
`web`.

Yang kedua kecil: bagian Persetujuan tinggal memuat rangkaian langkahnya.

---

## 1. Temuan

### 1a. Pengajuan mana yang punya file

Dari atribut PII di API eksternal (`ExternalRawDataService`):

| Resource | Kolom file | Isi di database tenant |
| --- | --- | --- |
| `medical-certificates` | `certificate_file` | `/uploads/medical/certificate_file-1789963794975-202926473.pdf` |
| `leaves` | `certificate_file` | (surat keterangan untuk cuti khusus) |
| `timesheets` | `photo_file` | (foto saat mengisi timesheet) |

Tiga jenis. Lembur, koreksi presensi, dan tukar shift tidak punya lampiran.

**Yang dikirim API cuma jalurnya**, bukan isi filenya — dan cermin Odoo bahkan
tidak menyimpan jalur itu: ia hanya ada di `raw_payload`. Jadi tidak ada satu pun
bagian dari rantai ini yang bisa menampilkan file sekarang.

### 1b. File unggahan dilayani tanpa autentikasi

```js
// index.js
app.use("/uploads", express.static(path.join(__dirname, "public/uploads")));
app.use("/uploads", async (req, res, next) => { /* proksi S3, tanpa auth */ });
```

Siapa pun yang tahu jalurnya bisa mengunduh surat dokter, foto KTP, kartu keluarga,
dan foto timesheet. Jalur itu tidak mudah ditebak (timestamp + angka acak), tetapi
**tidak ada pemeriksaan apa pun** — dan jalurnya ikut terkirim di respons API yang
sudah terautentikasi, sehingga pemegang kunci API bisa membagikannya ke luar.

Ini bukan bagian dari permintaan Anda, tetapi bersinggungan langsung: cara paling
wajar memberi Odoo akses ke file itu adalah endpoint berautentikasi — dan begitu
endpoint itu ada, jalur statisnya bisa ditutup.

### 1c. Panel kanan itu milik modul `mail`

```
addons/mail/static/src/chatter/web/chatter_patch.js:  "hasAttachmentPreview?"
addons/mail/static/src/chatter/web/chatter_patch.js:  hasAttachmentPreview: false
```

Panel pratinjau lampiran adalah bagian dari chatter di modul `mail`, dan ia terbuka
sendiri ketika catatan punya satu lampiran yang bisa dilihat. Tanpa `mail`, lampiran
`ir.attachment` tidak punya tempat untuk muncul di form.

---

## 2. Rancangan

### 2a. Backend: endpoint unduh berautentikasi

`GET /api/external/v1/files/download?path=<jalur>` — memakai rantai guard yang sama
dengan endpoint lain (kunci API + tenant + rate limit), membaca lewat
`StorageService` (lokal maupun S3), dan **menolak jalur di luar `public/uploads`**
(penjagaan path traversal, karena `..` di parameter akan membaca berkas lain di
server).

Kendali PII: berkas hanya keluar bila `include_pii=true`, sama seperti kolom PII
lainnya — atau lebih tegas: selalu memerlukan `include_pii=true`, karena isinya
selalu pribadi.

Setelah itu, **tutup jalur statis `/uploads`** dan arahkan pembacanya ke endpoint
baru. Kalau ada konsumen lain (aplikasi mobile), mereka harus diberi tahu lebih
dulu — ini yang perlu Anda putuskan (§5).

### 2b. Odoo: cermin lampiran

1. **Simpan jalur file di cermin** (`certificate_file` / `photo_file` sebagai
   `Char`), bukan hanya di `raw_payload`. Tanpa itu, penarikan berikutnya tidak
   bisa tahu apakah filenya berubah.
2. **Unduh sekali per jalur, lalu lampirkan.** Saat penarikan menemukan jalur yang
   berbeda dari yang tersimpan, unduh isinya dan simpan sebagai `ir.attachment`
   dengan `res_model`/`res_id` menunjuk baris cerminnya. Filestore Odoo
   **mendeduplikasi isi yang sama**, jadi membuat lampiran baru untuk baris yang
   ditulis ulang tidak menggandakan berkasnya.
3. **Jangan unduh ulang yang tidak berubah.** Penarikan berjalan tiap 15 menit dan
   setiap kali halaman dibuka; tanpa penjagaan ini, satu cermin yang stabil akan
   mengunduh berkasnya terus-menerus.
4. **Bersihkan lampiran saat barisnya hilang.** Cermin berperiode diganti per
   rentang dan dibersihkan jendela bergulir. `ir.attachment` tidak ikut terhapus
   bersama recordnya, jadi tanpa pembersihan ini lampiran menumpuk tanpa batas.
5. **Batas ukuran** (mis. 10 MB) dan jenis yang dikenali; yang lebih besar
   dilaporkan, bukan didiamkan.

### 2c. Odoo: cara menampilkannya

Panel kanan menuntut chatter, dan chatter menuntut `mail.thread` pada modelnya.

Bentuknya persis begini — dibaca dari `mail/static/src/chatter/web/form_compiler.js`:

```xml
<form>
    <!-- Penanda inilah yang menyalakan panel pratinjau: compiler chatter membaca
         keberadaan elemen ini, bukan isinya. -->
    <div class="o_attachment_preview"/>
    <sheet>…</sheet>
    <!-- `open_attachments` membuat kotak berkasnya langsung terbuka; tanpa itu
         pengguna menekan paperclip dulu. -->
    <div class="oe_chatter">
        <field name="message_follower_ids"/>
        <field name="message_ids" open_attachments="True"/>
    </div>
</form>
```

Tanpa elemen `o_attachment_preview` itu, chatter tetap ada tetapi panel kanannya
tidak pernah muncul.

**Keputusan: dikerjakan di modul inti `presenly_saas`.** Usulan awal saya adalah
modul terpisah mengikuti pola `presenly_saas_hr`; setelah diperiksa, itu kalah
argumen.

| Pilihan | Yang pengguna lihat | Ongkos sebenarnya |
| --- | --- | --- |
| **`mail` di modul inti** | paperclip + panel pratinjau kanan | `mail` jadi dependensi tetap; di instalasi yang sudah punya `mail` (praktis semuanya — di database uji pun `mail`, `bus`, `base_setup`, `web_tour`, `html_editor` sudah terpasang) ongkosnya nol |
| Modul terpisah | sama | satu instalasi tambahan yang harus diingat; lupa memasangnya berarti lampirannya diam-diam tidak muncul |
| Tanpa `mail`: One2many ke `ir.attachment` | daftar lampiran, pratinjau di jendela terpisah | tidak ada panel kanan — tidak sesuai permintaan |

Alasan memilih modul inti:

- **Jalur filenya bagian dari muatan yang dicerminkan.** Field-nya tetap harus ada
  di modul inti, karena `_mirror_values` yang mengisinya. Memisahkan hanya
  tampilannya membuat satu fitur tinggal di dua modul.
- **`mail.thread` tidak menambah perilaku bisnis apa pun di sini.** Modul ini tidak
  pernah memanggil `message_post` (nol rujukan di seluruh kode), jadi tabel pesan
  dan pengikutnya tetap kosong untuk model cermin — yang bertambah hanya kolom dan
  baris lampiran.
- **Pemisahan `presenly_saas_hr` dulu karena alasannya berbeda.** `hr` adalah
  aplikasi bisnis dengan model dan semantiknya sendiri (kontrak, cuti, kehadiran)
  yang tidak pantas dipaksakan ke setiap tenant. `mail` adalah prasarana yang
  dipakai tampilan cermin, bukan aplikasi yang pendapatnya ikut masuk ke data.
- **Satu modul, satu tempat memasang.** Kalau fitur ini opsional, dukungannya jadi
  pertanyaan berulang: "kok lampirannya tidak muncul" — jawabannya "modul
  dokumennya belum dipasang".

Konsekuensi yang diterima, dan sebaiknya tercatat:

1. `mail` (beserta `base_setup`, `bus`, `web_tour`, `html_editor`) menjadi
   dependensi tetap `presenly_saas`.
2. Chatter-nya dibuat **minimal**: hanya daftar pesan dengan lampirannya, tanpa
   pengikut dan tanpa aktivitas. Composer tetap muncul bagi pengguna yang boleh
   menulis, dan itu diterima sebagai tempat mencatat — modelnya tetap tidak bisa
   disunting dari Odoo.
3. Tabel pesan dan pengikut tidak ikut tumbuh selama modul tidak memposting apa pun.

Berkasnya: chatter pada tiga form (cuti, surat dokter, timesheet), field jalur
file di cermin, unduhan dan lampirannya, serta pembersihannya — semuanya di
`presenly_saas`.

### 2d. Bagian Persetujuan: hanya langkahnya

Yang **dihapus** dari form (field-nya tetap ada di model, jadi tidak ada data yang
hilang — hanya tidak ditampilkan):

- ringkasan alur: `approval_flow_status`, `approval_current_level`,
  `approval_total_levels`, `approval_waiting_for`
- keputusan pada pengajuannya sendiri: `approver_name`, `approved_at`,
  `tl_approver_name`, `tl_approved_at`, `manager_approver_name`,
  `manager_approved_at`, `rejecter_name`, `rejected_at`, `rejection_reason`
- dua catatan bertulisan yang menjelaskan ketiadaan level

Yang **tinggal**: rangkaian langkah (`approval_step_ids`) — nomor, nama penyetuju
yang diharapkan, status, siapa yang memutuskan dan kapan, serta alasan penolakan
per langkah. Keterangan per langkah itu bagian dari rangkaiannya, bukan keterangan
tambahan; kalau ikut dihapus, langkahnya tinggal nomor tanpa arti.

Kalau jenis pengajuan itu tidak punya alur, bagiannya **disembunyikan** — sekarang
isinya akan benar-benar kosong, dan judul kosong lebih membingungkan daripada tidak
ada judul.

---

## 3. Yang perlu Anda putuskan

1. ~~Modul terpisah atau `mail` di modul inti?~~ **Diputuskan: modul inti** (§2c).
   Yang tersisa untuk Anda setujui: `mail` menjadi dependensi tetap `presenly_saas`.
2. **Menutup `/uploads` sekarang atau nanti?** Menutupnya memutus tautan langsung
   yang mungkin masih dipakai aplikasi mobile atau web. Usulan: endpoint
   berautentikasi dulu, jalur statis ditutup setelah dipastikan tidak ada pemakai.
3. **Kolom PII di pengajuan**: apakah lampiran ikut ditarik pada penarikan biasa,
   atau hanya bila `include_pii=true` disetel di koneksi? Usulan: hanya bila
   disetel — isinya selalu pribadi.
4. **Batas ukuran lampiran** (usulan 10 MB) dan apakah file di atas batas itu
   dilaporkan di Sync Log.

---

## 4. Rencana kerja

| Fase | Isi | Perkiraan |
| --- | --- | --- |
| 1 | Endpoint unduh berautentikasi + penjagaan path traversal + tes | ½ hari |
| 2 | Simpan jalur file di cermin + unduh sekali + lampiran Odoo + tes | 1 hari |
| 3 | Chatter pada tiga form di modul inti + pembersihan lampiran | 1 hari |
| 4 | Bagian Persetujuan: sisakan langkahnya + perbarui tes yang menguncinya | ½ hari |
| 5 | (Terpisah) tutup `/uploads` setelah dipastikan tidak ada pemakai | ¼ hari |

Fase 4 bisa dikerjakan lebih dulu dan berdiri sendiri kalau Anda ingin cepat.

---

## 5. Rencana uji

| Yang diuji | Cara |
| --- | --- |
| Unduhan butuh kunci API | panggil tanpa kunci → 401 |
| Tenant lain ditolak | panggil dengan kunci tenant lain → 403 |
| Path traversal ditolak | `?path=../../.env` → 400, bukan isi berkas |
| Jalur di luar `public/uploads` ditolak | `?path=/etc/passwd` → 400 |
| Lampiran terpasang di baris cermin | unduh, periksa `ir.attachment` menunjuk baris yang benar |
| Tidak diunduh ulang | tarik dua kali, hitung pemanggilan unduhan: satu |
| Ganti file ikut terunduh | ubah jalurnya, tarik, lampirannya berganti |
| Lampiran ikut terhapus | hapus baris cermin, lampirannya hilang |
| Lewat batas ukuran dilaporkan | berkas besar → pesan di Sync Log, bukan gagal senyap |
| Bagian Persetujuan hanya langkah | arsip form tidak memuat field ringkasan dan field keputusan |
| Tanpa alur, bagiannya tidak tampil | `invisible` pada seluruh bagian |

---

## 6. Yang sengaja tidak dikerjakan

- **Menampilkan file tanpa menyimpannya di Odoo** (lampiran bertipe URL ke
  `/uploads`). Itu membiarkan PII terbuka tanpa autentikasi, dan panel pratinjau
  Odoo akan memuatnya lintas asal.
- **Menyimpan lampiran untuk presensi dan referensi.** Keduanya tidak punya file.
- **Menghapus field keputusan dari model.** Yang diminta adalah tidak
  menampilkannya; datanya masih dipakai daftar, pivot, dan ekspor.
