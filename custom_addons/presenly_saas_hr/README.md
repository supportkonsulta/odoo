# Presenly SaaS: HR Integration

Menambahkan integrasi pegawai pada modul `presenly_saas`: sinkronisasi dua arah
dengan `hr.employee`, dan pemberitahuan perubahan dari server Presenly.

## Kenapa modul terpisah

`presenly_saas` dipakai semua tenant; HR hanya sebagian. Dependensi `hr` menarik
`resource`, `resource_mail`, `phone_validation`, dan `mail` — memasangnya di modul
inti berarti setiap instalasi ikut memuatnya, walaupun tidak ada pegawai yang
disinkronkan.

Ada alasan praktis yang lebih mendesak: pada database yang pernah memuat modul
lain, tabel `hr` bisa saja sudah ada dalam keadaan tidak lengkap. Memaksa `hr` di
modul inti membuat seluruh instalasi gagal karena masalah yang tidak ada
hubungannya dengan langganan.

## Penolakan `hr_attendance` dan `hr_holidays`

Modul ini **menolak dipasang** bersama keduanya. Absensi dan cuti sudah
dicerminkan dari Presenly; kalau keduanya aktif, satu kejadian tercatat dua kali
dan tidak jelas mana yang benar.

Penolakannya lewat `excludes` di manifest, jadi ditegakkan Odoo sendiri dan
berlaku dua arah. Pesannya apa adanya dari Odoo:

```
Modules "Presenly SaaS: HR Integration" and "Attendances" are incompatible.
```

**Perlu diperhatikan sebelum memasang:** `hr_attendance` dan `hr_holidays` harus
dilepas lebih dulu, dan melepas `hr_holidays` menghapus data cuti yang ada di
Odoo. Kalau data itu masih dibutuhkan, jangan dipasang di database yang sama.

## Isinya

| Bagian | Keterangan |
|---|---|
| `presenly.saas.employee` | cermin apa adanya dari `GET /v1/employees`, termasuk kolom tanpa padanan di Odoo |
| `hr.employee` | ditambah `presenly_nopeg`, `presenly_synced_values`, `presenly_source_updated_at`, `presenly_synced_at` |
| Tombol **Pull Employees** | di halaman Langganan |
| Menu **Employees (mirror)** | di Referensi, untuk memeriksa kiriman server |
| Cron **Sync Employees** | harian, jaring pengaman tarikan |
| Penerima webhook | `/presenly_saas/webhook/<token>`, satu-satunya endpoint publik |

## Cara kerja sinkronisasi

Yang dipetakan **hanya kolom yang ada di kedua sisi**. Aturan konfliknya
**tidak** membandingkan jam dua server — itu tidak bisa dilakukan dengan andal.
Yang dibandingkan adalah nilai di kedua sisi terhadap snapshot terakhir
(`presenly_synced_values`):

| Odoo vs snapshot | Presenly vs snapshot | Tindakan |
|---|---|---|
| sama | sama | tidak ada |
| beda | sama | kirim Odoo → Presenly |
| sama | beda | terapkan Presenly → Odoo |
| beda | beda | bentrok: Presenly menang, **dilaporkan** |

Arah Odoo → Presenly dikirim **saat disimpan** (setelah commit), bukan menunggu
jadwal. Arah sebaliknya lewat webhook, dengan tarikan harian sebagai jaring
pengaman.

Tiga hal yang disengaja dan mudah dikira bug:

1. **Pegawai tidak pernah dihapus.** Tidak ada yang hilang dari `hr.employee`
   hanya karena satu tarikan tidak memuatnya.
2. **Nopeg ganda tidak dipilihkan salah satu.** Dua pegawai dengan nopeg sama
   membuat keduanya tidak disentuh, dan keadaannya dilaporkan.
3. **Menonaktifkan pegawai yang punya akun pengguna ditolak**, dan dilaporkan
   untuk diputuskan manual. Menonaktifkan berarti mencabut akses orang itu tanpa
   peringatan di Odoo.

## Pemberitahuan perubahan (webhook)

Tombol **Daftarkan Odoo Ini** di Settings mendaftarkan alamat penerima ke server
dan menyimpan rahasianya. Yang perlu diketahui:

- Alamatnya diambil dari `web.base.url`, jadi harus bisa dijangkau server.
- Dua lapis pengamanan: token acak di dalam alamat, dan tanda tangan HMAC-SHA256
  atas `<cap waktu>.<badan permintaan>`.
- Cap waktu dibatasi ±5 menit, supaya panggilan sah yang bocor tidak bisa dipakai
  ulang.
- Badan permintaannya **hanya penanda** `{event, nopeg, id, updated_at}`. Tidak
  ada data pegawai, jadi tidak ada PII lewat jalur publik dan isinya tidak
  pernah basi.
- Kegagalan dikirim ulang sampai 5 kali dengan selang melebar.

## Pengujian

```bash
odoo-bin -d <db> -i presenly_saas_hr \
  --addons-path=odoo/addons,addons,custom_addons \
  --test-enable --test-tags=/presenly_saas,/presenly_saas_hr \
  --stop-after-init --no-http
```

60 kasus uji: cermin dan penautan pegawai, aturan status aktif, kiriman balik
saat disimpan, penerimaan webhook beserta setiap cara penolakannya, dan batas
modul.

## Pemetaan kolom

Rincian lengkap dan keputusan yang mendasarinya ada di
[`PLAN_HR_SYNC.md`](./PLAN_HR_SYNC.md).

## Lokasi kerja menjadi `hr.work.location`

Presenly menyimpan lokasi beserta geofence-nya; Odoo punya model native untuk lokasi
kerja tetapi **tanpa koordinat maupun radius**. Karena itu ada dua lapis:

1. **`res.partner`** untuk alamatnya. `hr.work.location` mewajibkan `address_id`,
   sedangkan Presenly mengirim alamat sebagai teks bebas.
2. **`hr.work.location`** untuk lokasinya, ditambah field `presenly_*` untuk
   geofence.

Ini melanggar aturan lama modul ("tidak mewarisi model bisnis native"), dan
pelanggarannya disengaja: aturan itu dibuat supaya presensi tidak menyeret Odoo ke
ranah HR, sedangkan di sini yang diminta justru integrasi native. Semua field
tambahannya berawalan `presenly_`, jadi tidak bertabrakan dengan field Odoo.

Setelannya `Sync Work Locations to Odoo`, mati secara bawaan.

Penarikan menulis ke model native dengan penanda `presenly_skip_push`. Tanpa itu,
setiap tarikan akan memicu kirim balik dan berputar tanpa henti — dan itu sempat
terjadi di sini, ketahuan sebelum sempat jalan.

## Penempatan pegawai menentukan perusahaan dan lokasi kerja

Payload pegawai **tidak** membawa klien maupun lokasi kerja. Keduanya hanya ada di
resource `placements`, yang juga satu-satunya sumber `is_primary`.

Perhatikan penamaan: resource itu menamai kliennya `internal_company` dan lokasinya
`location`, bukan `tenantClient`/`workLocation` seperti nama asosiasi Sequelize-nya.
Nama itu sudah diganti fungsi `map` di `ExternalRawDataService.js`. Salah membaca
nama keluaran pernah membuat seluruh penempatan terbaca kosong, padahal datanya
lengkap.

Satu pegawai bisa punya beberapa penempatan. `hr.employee` hanya bisa menunjuk satu
perusahaan dan satu lokasi, jadi yang dipakai adalah penempatan yang **utama** dan
masih berlaku. Kalau tidak ada yang utama, tautannya dibiarkan apa adanya dan
keadaannya dicatat — menebak di antara beberapa penempatan menghasilkan tautan yang
salah tanpa jejak.

## Cabang per pegawai, dan akses perusahaan pengguna

Penempatan utama hanya satu, tetapi **cabangnya bisa beberapa**: satu baris
`placements` per pegawai dan klien. Karena itu:

- `hr.employee.presenly_client_ids` berisi **seluruh** perusahaan cabang dari
  penempatan yang berlaku hari ini (aktif, sudah mulai, belum berakhir). Daftarnya
  adalah keadaan sekarang, jadi cabang keluar dari daftar begitu penempatannya
  berakhir.
- Pengguna yang tertaut ke pegawai itu (`hr.employee.user_id`) mendapat perusahaan
  cabangnya di daftar **Perusahaan** miliknya, sehingga pemilih perusahaan berisi
  cabangnya dan ia bisa bekerja di sana.

Aturan yang dipegang, dan ini keputusan pemilik:

| Keadaan | Yang terjadi |
| --- | --- |
| Penempatan baru muncul | Perusahaannya ditambahkan ke daftar perusahaan pengguna, dan dicatat di log sinkronisasi |
| Penempatan berakhir | Cabangnya keluar dari daftar cabang pegawai, tetapi **akses perusahaannya dibiarkan** |
| Akses dihapus orang di Odoo | Tarikan berikutnya menambahkannya kembali; sinkronisasi hanya menambah, tidak pernah mencabut |
| Klien belum ada sebagai perusahaan | Tidak diberikan, dan keadaannya dihitung di ringkasan (`unknown_company`) |
| Perusahaan bukan hasil cermin klien | Tidak pernah ditambahkan |
| Perusahaan bawaan pengguna (`res.users.company_id`) | Tidak diubah; perpindahan hanya lewat pemilih perusahaan |
| Tarikan terpotong | Daftar cabang tidak disentuh sama sekali |

Alasannya: kehilangan perusahaan di tengah pekerjaan tanpa diminta lebih
merugikan daripada akses yang tertinggal sedikit lebih lama. Karena itu modul ini
**menulis ke `res.users`**, yaitu model native yang sebelumnya tidak pernah
disentuh; yang ditulis hanya kolom `company_ids`, tidak ada kolom native yang
diubah artinya.

## Kirim balik lokasi kerja

Setelannya `Send Work Location Edits to Presenly`, mati secara bawaan. Aplikasi
tetap pemilik data lokasi kecuali seseorang memutuskan lain.

Yang dikirim hanya **kolom yang benar-benar disunting**, karena endpoint tujuannya
memang menerapkan semantik itu: kolom yang tidak dikirim tidak disentuh di sana.
Mengirim seluruh objek justru berbahaya — ia akan mengosongkan kolom yang tidak
diikutkan.

Pembuatan lokasi **tidak** ada di endpoint itu. Lokasi baru tetap dibuat dari
aplikasi, karena di sanalah lokasi ditetapkan ke klien dan proyek; memindahkan
lokasi antar klien dari integrasi berarti melewati alur yang memeriksa hak akses.

Dua kesalahan yang ditemukan di jalur ini, keduanya berbahaya karena **tidak
berbunyi**: pencarian konfigurasi per perusahaan (lokasi milik perusahaan cermin
klien, sedangkan konfigurasi dimiliki perusahaan pemasang) membuat kirim balik
tidak pernah terkirim tanpa galat apa pun; dan jalur yang saya tulis
(`/api/external/v1/...`) menggandakan prefiks karena `_request` sudah menambahkannya.

## Tautan pegawai dan lokasi pada pengajuan

Cabang saja belum cukup untuk payroll: yang dihitung adalah lembur **seorang
pegawai** di **sebuah lokasi kerja**. Baris cermin pengajuan karena itu menyimpan
tiga tautan:

| Kolom | Menunjuk ke | Dicocokkan lewat |
| --- | --- | --- |
| `tenant_location_id` | `presenly.saas.work.location` | `location.id` di payload ke `external_id` lokasi |
| `hr_work_location_id` | `hr.work.location` | `presenly_external_id` lokasi itu |
| `hr_employee_id` | `hr.employee` | nomor pegawai (`nopeg`) di payload ke cermin pegawai |

Ketiganya diisi dari hook yang sama, dijalankan **sekali per tarikan** dan
sekaligus untuk semua baris - bukan satu kueri per baris. Cermin bisa berisi
ribuan baris, dan pencarian per baris membuat tarikan melambat tanpa terlihat
sebabnya.

Aturan yang dipegang:

- **Sekali isi.** Tautan hanya diisi kalau masih kosong, sama seperti cabang.
  Pengajuan adalah catatan masa lalu; pegawai yang pindah lokasi bulan depan tidak
  boleh memindahkan lembur bulan lalu.
- **Lokasi dipilih menurut perusahaan cabangnya.** Kalau ada beberapa
  `hr.work.location` dengan id Presenly yang sama, yang dipakai adalah yang
  perusahaannya sama dengan perusahaan cabang baris itu. Kalau tidak ada yang
  cocok, kolomnya dibiarkan kosong dan jumlahnya dicatat di log - lokasi yang salah
  membuat payroll menagih ke cabang yang salah, dan itu tidak terlihat.
- **Nama tidak pernah dipakai untuk mencocokkan.** Di lapangan ada lokasi bernama
  sama di dua cabang.
- **Kolom lokasi native dipakai apa adanya.** `hr_work_location_id` diisi langsung
  dari `location_id` bila tautannya sudah ada, tanpa menunggu cermin lokasi.

Modul ini sengaja **tidak** menambah model baru untuk tautan ini: yang ditambahkan
hanyalah kolom pada model pengajuan yang sudah ada, lewat mixin
`presenly.saas.submission.hr.mixin`. Mixin itu dinamai `...mixin` supaya tidak
diminta punya aturan akses sendiri, karena ia tidak pernah ditampilkan.

Empat kunci yang dibutuhkan payroll dibuktikan bisa dijawab dari baris cermin oleh
`tests/test_submission_payroll_ready.py`: `employee_id`, `state`, rentang
tanggalnya, dan `work_location_id`. `hr_payroll_custom` sendiri tidak disentuh.

## Data milik sendiri

Pegawai perlu melihat presensi dan pengajuannya sendiri, dan sebelumnya itu tidak
mungkin: menu Presenly hanya untuk Manager, dan aturan pengajuan memberi pengguna
internal **satu cabang penuh** - artinya rekan sekerja ikut terlihat.

Dua hal dikerjakan bersama, dan keduanya harus ada:

1. Menu akar, Attendance, dan Requests dibuka untuk pengguna internal. Menu yang
   bukan untuk mereka dikunci sendiri (Monitoring, Subscription, Reference,
   Timesheet, Sync Log), karena menu yang induknya tersaring grup tetap muncul
   sebagai butir lepas.
2. Aturan "milik sendiri" ditambahkan untuk cermin presensi dan kelima jenis
   pengajuan, dan grup internal **dikeluarkan** dari aturan cabang. Tanpa langkah
   kedua ini aturan barunya tidak mengubah apa pun: aturan grup digabung dengan
   OR, jadi satu aturan cabang yang masih menyebut pengguna internal cukup untuk
   membuat semua rekan sekerja terlihat kembali. Aturan cabangnya diserahkan ke
   grup Approver, yang memang memutuskan pengajuan.

Kuncinya `res.users.presenly_nopeg`, bukan `user.employee_id`:
`employee_id` adalah pegawai pada **perusahaan yang sedang aktif**, sedangkan
record pegawai di sini berada di perusahaan integrasi. Aturan yang memakai
`employee_id` akan buta bagi pegawai yang sedang bekerja di perusahaan cabang.

Aturan "milik sendiri" sengaja **tidak** berpagar perusahaan. Pengguna cabang tidak
punya perusahaan integrasi di daftar perusahaannya - di basis nyata, `yusril` hanya
punya CLIENT 1 dan CLIENT 2, sedangkan semua baris cermin berada di perusahaan
integrasi - jadi pagar itu akan membuatnya kehilangan datanya sendiri. Batas tenant
dijaga oleh aturan pengelola, Approver, dan HR, ditambah awalan tenant pada nopeg.

Pengguna yang belum tertaut ke pegawai melihat nol baris, bukan semuanya. Domainnya
memakai sentinel `'__tanpa_nopeg__'` supaya baris yang nopeg-nya kosong tidak ikut
cocok.

## Memutuskan pengajuan dari Odoo

Cermin pengajuan bersifat baca saja: keputusan tetap milik Presenly. Yang bisa
dilakukan dari Odoo adalah **mengirim keputusan** ke sana, dan hanya bila pemilik
data menyalakannya (`Decide Requests from Odoo` pada konfigurasi koneksi, mati
secara bawaan - keputusan itu meninggalkan aplikasi).

Yang dikirim hanya tiga hal: `actor_nopeg`, `decision`, `level`. Identitas pembuat
keputusan adalah **nopeg**, bukan id pengguna Odoo, karena di sanalah aplikasi
mengenal orang. Karena itu nopeg yang salah atau kosong bukan sekadar kolom yang
belum diisi: keputusannya akan tercatat atas nama orang lain, atau ditolak.

Yang berhak menekan tombol bukan "siapa pun yang bisa membuka menunya", melainkan
satu orang: pemegang langkah yang **sedang berjalan**. Langkahnya disalin dari
payload, lengkap dengan `level`, `approver_type`, dan `expected_nopeg`. Tiga
keadaan karena itu tidak punya tombol sama sekali, dan itu disengaja - lebih baik
tidak ada tombol daripada tombol yang ditolak:

| Keadaan | Kenapa |
|---|---|
| Langkahnya milik sekumpulan orang (`role`, `permission`) | Yang berhak bukan satu orang, jadi tidak ada satu pengguna Odoo yang bisa ditunjuk |
| Atasan langsungnya belum punya akun Odoo | Sama: tidak ada orangnya |
| Jenis pengajuannya belum dilayani | Ditentukan `RESOURCE_BY_MODEL`. Kelimanya sudah dilayani: `leaves`, `overtimes`, `medical-certificates`, `attendance-corrections`, `shift-swaps` |

Kolom `Approver Now` menunjukkan siapa yang ditunjuk untuk langkah berjalan, dan
`You May Decide` hanya menyala untuk orang itu.

Tiga penjagaan dijalankan berurutan saat tombolnya ditekan, dan masing-masing
punya pesannya sendiri:

| Penjagaan | Pesan |
|---|---|
| Setelan `Decide Requests from Odoo` menyala untuk perusahaan yang aktif | "Deciding requests from Odoo is not enabled..." |
| Pengguna punya nopeg | "Your Odoo user is not linked to a Presenly nopeg..." |
| Pengguna memang pemegang langkah yang berjalan | "You are not the approver for the level that is running now..." |

**Nopeg untuk keputusan dibaca dari `res.users.presenly_nopeg`, bukan dari
`user.employee_id.presenly_nopeg`.** `employee_id` adalah pegawai pada perusahaan
yang **sedang aktif**, sedangkan record pegawai di sini berada di perusahaan
integrasi. Pengguna cabang - yang perusahaan aktifnya perusahaan cabang, dan yang
memang tidak punya perusahaan integrasi - karena itu dicap "belum tertaut nopeg"
walaupun nopegnya sudah terisi, dan itu satu-satunya yang menghalanginya
memutuskan. Perilakunya diuji di `tests/test_own_data_rules.py`.

### Salinan yang tertinggal

Cermin bisa tertinggal dari kenyataan: keputusan level sebelumnya bisa diambil
dari aplikasi, sedangkan pemberitahuan perubahannya tidak selalu sampai ke Odoo.
Salinan yang tertinggal tidak berbahaya selama tidak dipakai untuk memutuskan —
dan di situlah ia berbahaya: level yang dikirim ikut yang tertinggal, lalu server
menolaknya dengan *"Level yang berjalan untuk pengajuan ini 2, bukan 1. Muat ulang
pengajuannya."*

Karena itu alurnya sekarang begini:

| Langkah | Kenapa |
|---|---|
| Perubahan terakhir ditarik **sebelum** keputusan dikirim | Levelnya jadi yang benar, bukan yang tertinggal |
| Kalau ternyata tidak ada lagi level berjalan, keputusannya tidak dikirim | Pengajuan itu sudah diputuskan orang lain; mengirimnya hanya menghasilkan penolakan |
| Ditolak server ⇒ perubahan ditarik lagi, lalu layarnya **dimuat ulang** | Pemberitahuan bisa membawa aksi muat ulang; `UserError` tidak |

Penyegarannya dijalankan di **transaksi tersendiri** yang commit sendiri
(`_refresh_recent_from_decision`). Bukan pilihan gaya: `UserError` membatalkan
transaksi yang sedang berjalan, jadi penyegaran yang ditulis di transaksi yang sama
akan ikut hilang bersama pesannya — dan layarnya kembali menampilkan keadaan yang
baru saja dibantah server.

Penolakan server karena itu dikembalikan sebagai **pemberitahuan**, bukan galat.
Perbedaannya bukan kosmetik: pemberitahuan bisa membawa aksi muat ulang, sedangkan
galat tidak, dan yang dibutuhkan pengguna di situasi ini adalah layar yang
menampilkan keadaan barunya.

### Kenapa salinannya bisa tertinggal

Pemberitahuan webhook (`leave.updated`) yang mendorong penyegaran itu **per
endpoint terdaftar**. Selama pendaftarannya masih menunjuk instance lain, tidak ada
yang memberi tahu Odoo bahwa pengajuannya berubah, dan yang menyegarkan hanya cron
— jadi salinannya bisa tertinggal sampai jadwal berikutnya. Gejalanya persis seperti
di atas: tombolnya masih ada pada level yang sudah lewat.

### Kesegaran di layar, dan syarat tombolnya

Daftar sudah menyegarkan dirinya saat dibuka (`web_search_read` di mixin cermin),
tetapi formulir membacanya lewat jalur lain - termasuk saat barisnya diklik dari
daftar.

Konfigurasi koneksinya dicari lewat `_config_for_company`, bukan lewat pencarian
langsung pada perusahaan yang sedang aktif. Pengguna cabang berperusahaan aktif
perusahaan cabang, dan di sana tidak ada konfigurasi apa pun; pencarian langsung
membuat penyegaran halaman diam-diam tidak pernah berjalan untuk mereka - daftar
maupun formulir - walaupun koneksinya menyala. Karena itu `web_read` pada cermin pengajuan ikut menyegarkan lebih dulu,
dengan batas jumlah record: membaca banyak baris sekaligus bukan membuka formulir,
dan penyegaran di situ tidak ada gunanya. Biayanya kecil, karena yang diperiksa
lebih dulu hanya "ada perubahan?", dan penarikan terjadi kalau memang ada.

Tombolnya ada di **kelima** form pengajuan - cuti, lembur, surat dokter, koreksi
presensi, tukar shift - dengan blok view yang sama. Bloknya tidak bisa ditulis
sekali lalu dipakai lima kali: arch view tidak menjalankan QWeb, jadi `t-call` di
sana tidak akan diperluas.

Tombol keputusannya punya empat syarat, dan keempatnya diperiksa **sebelum**
tombolnya muncul:

| Syarat | Kalau tidak terpenuhi |
|---|---|
| Jenis pengajuannya dilayani | Catatan: jenis ini belum bisa diputuskan dari Odoo |
| Setelan `Decide Requests from Odoo` menyala | Catatan: setelannya masih mati, beserta cara menyalakannya |
| Pengguna punya nopeg | Catatan: nopegnya belum diisi, dan Presenly mengenali pemutusnya dari nopeg |
| Pengguna memang pemegang level yang berjalan | Tidak ada catatan |

Catatan itu hanya muncul untuk orang yang **berhak** di level yang berjalan.
Pembedaannya disengaja: pengguna lain tidak mencari tombol itu, jadi menjelaskan
kenapa tombolnya tidak ada hanya menambah kebisingan. Yang berhak, sebaliknya,
tidak perlu menekan tombol lebih dulu untuk tahu apa yang menghalanginya.

### Kabar ke layar yang sedang terbuka

Pengajuan bisa diputuskan di aplikasi, dan cermin di Odoo baru mengetahuinya saat
ditarik. Ketika tarikan itu menulis perubahan status atau level, yang dikabari
lewat bus hanya **dua orang**: pemohonnya, dan pemegang level yang sedang
berjalan. Menyiarkannya ke semua pengguna berarti memberi tahu bahwa pengajuan itu
ada, lengkap dengan statusnya.

Isi pesannya **data**, bukan kalimat yang sudah dirangkai: `model`, `id`, status,
level, total level, dan siapa yang ditunggu. Kalimatnya disusun di sisi klien
(`static/src/submission_notice/`), supaya bahasanya bahasa penerima, bukan bahasa
proses sinkronisasi yang kebetulan sedang menjalankan tarikan.

Pesan itu muncul sebagai dialog **bawaan Odoo**, sesuai tingkatannya: `AlertDialog`
untuk pemberitahuan, `WarningDialog` untuk peringatan, dan `ErrorDialog` untuk
galat. Dialog buatan sendiri tidak dipakai: bentuk, ukuran huruf, dan tombolnya
sudah dikenal pengguna, dan tidak ada yang perlu dirawat di sini.

Layarnya **disegarkan sendiri**, tetapi hanya ketika yang sedang dibuka adalah
**record itu sendiri**. Pengguna lain yang kebetulan membuka daftar tidak
diganggu: memuat ulang daftar membuang posisi gulir dan pencariannya, dan itu
kerugian yang tidak sebanding dengan kabar yang bisa dilihat kapan saja. Formulir
cermin juga hanya-baca, jadi memuat ulangnya tidak mungkin membuang isian siapa
pun.

Efek sampingnya yang justru diminta: sesudah level itu diputuskan, tombol
**Approve/Reject** hilang dengan sendirinya. Tombolnya muncul dari perhitungan atas
level yang sedang berjalan, dan penyegaran itulah yang membuat hitungannya ulang.

Hal yang sama berlaku untuk jalur tombol: keputusan yang ditolak server dijelaskan
lewat dialog bawaan yang sama, bukan toast. Toast menghilang sendiri, dan pesan
yang hilang sebelum dibaca sama saja dengan tombol yang tidak bekerja.

## Pemberitahuan perubahan

`employee.created/updated`, `client.created/updated`, `work_location.created/updated`.

Hooknya dipasang di tingkat model, bukan di tiap controller: data ini bisa berubah
dari pendaftaran mandiri, profil mobile, panel admin, dan API eksternal, sehingga
satu tempat yang terlewat akan membuat integrasi diam-diam tidak sinkron.

Payloadnya hanya penanda (`{event, id, updated_at}`), tanpa isi data. Penerima
mengambil sendiri lewat API terautentikasi, jadi tidak ada nama klien maupun alamat
lokasi yang melintas ke luar atau tersimpan di riwayat pengiriman.

Penerima di Odoo mengarahkan per peristiwa. Sebelumnya semua peristiwa menarik
pegawai: perubahan klien memicu penarikan pegawai yang tidak ada hubungannya, dan
perubahan lokasi kerja tidak pernah menyalin lokasinya. Peristiwa tanpa nama
(pengirim lama) dan nama yang belum dikenal tetap ke pegawai — itu tarikan yang
paling penting.

Endpoint yang **sudah terdaftar** perlu didaftarkan ulang agar keenam peristiwa
berlaku. Selama belum, fiturnya ada tetapi diam.

## Rekonsiliasi sisi bridge

Untuk pegawai, hasilnya lebih tajam daripada lokasi: sinkronisasi pegawai menyimpan
snapshot nilai terakhir yang disepakati, sehingga bisa dibedakan **"berbeda"** dari
**"berubah di kedua sisi"**. Yang kedua itu yang berbahaya — sinkronisasi memilih
nilai Presenly, dan tanpa laporan ini suntingan Odoo hilang tanpa jejak.

Untuk lokasi tidak ada snapshot, jadi yang dilaporkan hanya "berbeda" beserta waktu
perubahan di kedua sisi. Saya tidak mengaku tahu mana yang lebih dulu berubah.

Kalau `Sync Work Locations to Odoo` mati, dataset lokasi dilewati seluruhnya.
Melaporkan setiap lokasi sebagai "hilang" bukan temuan, itu setelan.

Satu hal yang mahal ditemukan di sini: `native['address_id.street']` **tidak**
didukung Odoo. Saya sempat mengira didukung dan menulis komentar yang mengklaim
begitu; galatnya menelan seluruh dataset lokasi sehingga tidak ada satu pun temuan
muncul.
