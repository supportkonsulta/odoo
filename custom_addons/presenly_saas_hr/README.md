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
