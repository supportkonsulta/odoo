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
