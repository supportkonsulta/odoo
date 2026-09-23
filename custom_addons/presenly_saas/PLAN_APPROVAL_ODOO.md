# Rencana: persetujuan berjenjang dikerjakan dari Odoo

Status: **rencana**, belum ada kode.

Tujuan: approver membuka Odoo, melihat pengajuan yang menunggu gilirannya, lalu
memutuskan — setuju atau tolak — tanpa membuka aplikasi Presenly.

---

## 1. Yang sudah ada, dan yang belum

Pertanyaan pertama bukan "bisa atau tidak", melainkan "apa yang sudah tersedia".
Ternyata sebagian besar sudah.

**Sudah ada di Odoo:**

| Bagian | Isi |
|---|---|
| `presenly.saas.approval.step.mixin` | satu baris per level, untuk lima jenis pengajuan |
| Kolom level | `level`, `step_status`, `approver_type`, `approver_value`, `expected_name`, `expected_nopeg`, `approver_label` |
| Kolom keputusan | `acted_by_name`, `acted_by_nopeg`, `acted_at`, `rejection_reason` |
| Kolom pengajuan | `approval_has_workflow`, `approval_flow_status`, `approval_current_level`, `approval_total_levels`, `approval_waiting_for` |
| Tampilan | widget rantai langkah (`presenly_approval_steps`), sudah menampilkan siapa, keadaan, dan keterangan |

Artinya Odoo **sudah tahu** siapa yang seharusnya menyetujui level berapa — lengkap
dengan nopeg-nya. Yang belum ada hanyalah kemampuan **memutuskan**.

**Sudah ada di Presenly:**

- Seluruh logika jenjang: konfigurasi alur, urutan level, siapa yang berhak, dan
  efek samping keputusan (saldo cuti, koreksi presensi yang diterapkan).
- API eksternal mengirimkan rantai itu sebagai kunci `approval` pada resource
  pengajuan — **hanya baca**.

**Belum ada:** endpoint tulis untuk keputusan. Route tulis di API eksternal saat ini
hanya untuk pegawai, lokasi kerja, webhook, dan upsert gaya lama.

Jadi celahnya tepat satu: **satu endpoint keputusan di backend**, yang memakai
layanan persetujuan yang sudah dipakai aplikasi.

---

## 2. Prinsip yang menentukan seluruh rencana ini

> **Odoo tidak menghitung jenjang. Server tetap satu-satunya yang berhak.**

Odoo hanya menampilkan rantai dan mengirim keputusan. Kalau Odoo ikut menghitung
siapa yang berhak di level berapa, akan ada dua implementasi aturan yang sama, dan
keduanya akan berbeda pendapat — persis kelas kesalahan yang berkali-kali muncul di
integrasi ini.

Konsekuensi praktisnya: tombol di Odoo adalah **kenyamanan**, bukan pengaman.
Pengamannya di server.

---

## 3. Persoalan yang harus dijawab lebih dulu

### 3.1 Identitas: siapa yang memutuskan

Satu kunci API mewakili satu tenant, bukan satu orang. Jadi server tidak bisa tahu
siapa yang menekan tombol hanya dari kunci itu — pemanggil harus menyebutkannya.

Rancangannya: badan permintaan membawa actor (`nopeg`), dan **server yang
memeriksa** apakah orang itu benar-benar berhak pada level yang sedang berjalan.
Klien tidak boleh dipercaya menyatakan haknya sendiri.

**Yang perlu diputuskan:** apakah nopeg cukup sebagai identitas, atau perlu email
sebagai cadangan bila nopeg tidak ada di sisi Odoo?

### 3.1b Jangan memakai `can_approve` untuk menentukan siapa yang berhak

`can_approve` pada payload pegawai adalah **flag tersimpan** di aplikasi, bukan
hak efektifnya. Hak efektif dihitung aplikasi saat dipakai:

```
can_approve efektif = flag tersimpan
                    OR peran = admin
                    OR terdaftar sebagai approver bertipe `user` di alur aktif
                    OR perannya terdaftar sebagai approver bertipe `role`
```

Bukti dari data tenant: `iksg-feri` adalah approver level 1 di kelima alur aktif,
tetapi flag tersimpannya `0`. Jadi kalau Odoo menentukan siapa yang boleh
menyetujui berdasarkan kolom ini, **Feri justru tidak akan bisa menyetujui apa
pun** — padahal di aplikasi ia approver pertama di semua alur.

Karena itu tombolnya ditentukan oleh **langkah persetujuan** (`expected`), bukan
oleh kolom ini. Kolom di `hr.employee` tetap ada sebagai keterangan, dengan nama
yang menyebut apa adanya: flag, bukan hak.

Kalau nanti memang perlu menampilkan "boleh menyetujui" secara akurat di Odoo,
yang benar adalah server mengirim nilai efektifnya — bukan Odoo menghitung ulang
aturan aplikasi.

### 3.2 Approver yang bukan orang tertentu

Server mengenal **empat** tipe approver: `user`, `direct_manager`, `role`, dan
`permission`. Yang dikirim sebagai orang **hanya `user`**.

Untuk tiga tipe lainnya, payloadnya cuma `{ type: ..., value: null, user: null }`
(lihat `test_external_approval.test.js`: *"atasan langsung tidak punya nilai
mentah"*). Sebabnya berbeda-beda, dan itu yang membuatnya bukan sekadar pekerjaan
pemetaan:

- **`direct_manager`** — siapa atasannya bergantung pada **pemohonnya**. Level 2
  pada satu konfigurasi menunjuk orang yang berbeda untuk tiap pengajuan, jadi
  "siapa approvernya" tidak bisa dikirim sebagai satu nilai.
- **`role` dan `permission`** — yang berhak adalah **sekumpulan orang**, bukan satu
  orang. Tidak ada satu orang pun yang bisa disebut sebagai approvernya.

Konsekuensinya di Odoo: tombol **Setujui** pada level seperti ini tidak bisa
ditampilkan ke satu pengguna tertentu berdasarkan data yang ada sekarang.

**Yang perlu diputuskan** (belum dijawab): apakah

- (a) server menyelesaikan `direct_manager` menjadi orangnya lalu mengirimkannya,
      dan `role`/`permission` dipetakan ke grup Odoo — sehingga tombolnya muncul
      untuk yang berhak; atau
- (b) level seperti itu tetap ditampilkan tetapi hanya bisa diputuskan dari
      aplikasi, sementara Odoo menangani level bertipe `user` saja.

Saran: (a) untuk `direct_manager` karena penyelesaiannya jelas dan satu orang,
tetapi (b) untuk `role`/`permission` — memetakan "siapa saja yang punya peran ini"
ke grup Odoo menuntut data peran yang belum tentu sama di kedua sisi, dan salah
petakan berarti menampilkan tombol kepada orang yang tidak berhak.

### 3.3 Hanya level berjalan, atau boleh melompat

Pilihan: Odoo hanya boleh memutuskan **level yang sedang berjalan**, atau juga
level lain sebagai override admin.

Saran: hanya level berjalan, ditambah override terpisah yang dicatat sebagai
override — mencampur keduanya membuat keputusan yang salah jalur terlihat biasa
saja.

### 3.4 Alasan penolakan

Saran: **wajib** untuk penolakan. API-nya sudah membawa alasan, dan penolakan tanpa
alasan memaksa orang membuka aplikasi untuk mencari tahu kenapa.

---

## 4. Bahaya yang harus ditangani sejak awal

### 4.1 Keputusan ganda

Pengajuan bisa diputuskan dari aplikasi lebih dulu. Kalau Odoo mengirim keputusan
untuk level yang sudah lewat, hasilnya dua keputusan untuk satu level.

Tangkalannya: keputusan bersifat **bersyarat** — pemanggil menyertakan level yang
dimaksud, dan server menolak bila levelnya sudah bergerak. Penolakannya dilaporkan
di Odoo, bukan didiamkan.

### 4.2 Efek samping

Menyetujui cuti mengubah saldo; menyetujui koreksi presensi menulis presensi.
Semuanya sudah ada di layanan aplikasi. Endpoint baru **memanggil layanan itu**,
tidak menuliskannya ulang. Kalau ditulis ulang, cepat atau lambat dua jalur itu
berbeda perilaku.

### 4.3 Kegagalan diam

Pelajaran dari fase-fase sebelumnya di integrasi ini: yang mahal bukan yang gagal
berisik, melainkan yang gagal tanpa suara. Setiap penolakan server — tidak berhak,
level sudah lewat, alasan kosong — harus muncul di layar Odoo sebagai pesan, bukan
sebagai tombol yang seolah tidak terjadi apa-apa.

### 4.4 Notifikasi

Menyetujui dari Odoo berarti jalur notifikasi aplikasi (pemberitahuan ke approver
berikutnya atau ke pemohon) harus tetap berjalan. Ini bagian dari layanan yang
dipanggil, jadi harus dipastikan, bukan diasumsikan.

### 4.5 Kebasian data

Modul ini sudah menyegarkan cermin saat halamannya dibuka. Itu tetap dipakai, dan
tombol keputusan hanya muncul berdasarkan data yang baru disegarkan — bukan berdasarkan
cermin yang bisa jadi sudah berumur satu periode.

---

## 5. Rancangan endpoint

Bentuknya mengikuti gaya yang sudah ada di API eksternal:

```
GET  /v1/approvals/contract
       -> { resources: [...], decisions: ['approve','reject'],
            requires_reason_on: ['reject'], condition: 'level' }

POST /v1/submissions/{resource}/{id}/decision
     { "actor_nopeg": "iksg-yusril",
       "decision": "approve",
       "level": 2,
       "reason": null }
       -> 200 { data: { status, approval_current_level, approval_total_levels, steps: [...] } }
       -> 403 actor tidak berhak pada level ini
       -> 409 level sudah bergerak / sudah diputuskan
       -> 400 alasan wajib untuk penolakan
```

`{resource}` memakai nama yang sudah dipakai API untuk pengajuan, supaya tidak ada
kosakata baru: `leaves`, `overtimes`, `attendance-corrections`,
`medical-certificates`, `shift-swaps`.

Balasannya mengembalikan keadaan baru rantai persetujuan, sehingga Odoo bisa
memperbarui langkahnya tanpa tarikan penuh.

---

## 6. Tahapan

Tiap tahap bisa diuji sendiri dan tidak meninggalkan setengah fitur.

### Tahap A — Backend, satu jenis pengajuan (cuti) — **selesai**

Bentuk yang dipakai:

```
GET  /v1/approvals/contract
POST /v1/submissions/{resource}/{id}/decision
     { actor_nopeg, decision, level, reason? }
```

Yang dikerjakan, dan yang menyimpang dari rencana di atas:

- Aktor diverifikasi di server; haknya diperiksa `WorkflowService.processApproval`
  lewat `LeaveService` — layanan yang sama dengan aplikasi, jadi urutan level, efek
  samping, dan notifikasinya tidak ditulis ulang.
- Keputusan bersyarat pada `level`: level yang tidak disebut ditolak 400, dan level
  yang sudah bergerak ditolak 409.
- Alasan penolakan **tidak wajib** (keputusan yang sudah diambil di §7).
- **Menyimpang dari rencana:** balasannya bukan rantai persetujuan yang baru,
  melainkan penanda `refresh_resource`. Rantai itu dibangun di satu tempat saja —
  pembentuk yang sama dengan tarikan — dan klien memuat ulang pengajuan lewat
  tarikan. Menyalin bentuknya ke endpoint keputusan berarti dua tempat yang harus
  dijaga tetap sama.

Dibuktikan pada server sungguhan, seluruhnya lewat jalur yang tidak mengubah data:
kontrak 200, nopeg tak dikenal 403, level tak disebut 400, pengajuan yang tidak
menunggu 409, dan keputusan untuk level yang salah 409 — dengan cutinya tetap
`pending` di level 2 sesudahnya. Kedua penolakan tercatat di audit beserta nopeg
yang mencoba dan levelnya.

### Tahap B — Odoo, tombol dan penautan

- Pemetaan approver ke pengguna Odoo lewat `hr.employee.presenly_nopeg` → `user_id`
  (kolom nopeg-nya sudah ada dari sinkronisasi pegawai, jadi tidak perlu tabel
  pemetaan baru).
- Tombol **Setujui** / **Tolak** muncul hanya untuk pengguna yang berhak pada level
  berjalan, dan hanya setelah cermin disegarkan.
- Penolakan server ditampilkan sebagai pesan di pengajuan.
- Setelah keputusan: penyegaran **hanya pengajuan itu**, bukan satu periode penuh.
- Tes: tombol muncul untuk orang yang tepat dan tidak muncul untuk yang lain;
  pengguna Odoo tanpa tautan nopeg tetap bisa melihat tetapi tidak bisa memutuskan;
  keputusan memperbarui langkahnya.

### Tahap C — Empat pengajuan lain

Lembur, koreksi presensi, sertifikat medis, tukar shift. Masing-masing punya efek
samping sendiri, jadi masing-masing perlu tesnya sendiri.

### Tahap D — Rekonsiliasi keputusan

Memakai layar rekonsiliasi yang sudah ada: keputusan yang terjadi di aplikasi
tetapi tidak pernah tercermin di Odoo. Ini yang menangkap keputusan yang hilang
ketika webhook tidak sampai.

### Tahap E — Opsional

Pengingat ke approver yang menunggu, dan tampilan "menunggu saya" di beranda Odoo.

---

## 7. Keputusan

Sudah dijawab:

1. **Identitas: nopeg saja.** Tidak ada email sebagai cadangan.
   Ikutannya sudah dikerjakan: kolom `Presenly Nopeg` di form pegawai kini bisa
   diisi manual dan **menautkan sendiri** — data cermin untuk nopeg itu langsung
   diterapkan. Nopeg yang belum pernah ditarik **ditolak**, dan nopeg yang sudah
   dipegang pegawai lain juga ditolak, karena dua pegawai dengan nopeg sama
   membuat sinkronisasi menolak menyentuh keduanya.
2. **Approver selain tipe `user`: belum diputuskan.** Penjelasannya di §3.2.
3. **Hanya level berjalan.** Tidak ada override admin di Odoo.
4. **Alasan penolakan tidak wajib**, sama seperti di aplikasi. Kalau alasan
   dikirim, ia diteruskan dan ditampilkan.
5. **Mulai dari cuti**, lalu pengajuan lain yang bersifat pengajuan: lembur,
   koreksi presensi, sertifikat medis, tukar shift.

Yang masih menunggu jawaban hanya nomor 2. Tahap A dan B bisa dimulai tanpa itu,
karena keduanya bekerja untuk level bertipe `user`.

---

## 8. Taksiran

Tahap A dan B sudah menghasilkan sesuatu yang bisa dipakai untuk satu jenis
pengajuan. Tahap C sebagian besar pengulangan dengan efek samping berbeda. Tahap D
memanfaatkan yang sudah ada.

Yang paling menentukan lama-tidaknya bukan jumlah pengajuan, melainkan jawaban atas
pertanyaan di bagian 7 — terutama soal identitas dan approver bertipe manajer.
