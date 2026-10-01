# Plan: Lokasi kerja pada pengajuan lembur, siap ditarik payroll

**Cakupan:** `backend_presenly`, `web_presenly`, `presenly_saas` + `presenly_saas_hr` (Odoo)
**Versi dokumen:** DRAFT v3
**Status:** RENCANA. Belum ada kode yang ditulis untuk dokumen ini.
**antislop:** DURING (ada perubahan tampilan di web dan di Odoo)
**Prasyarat:** tiga keputusan di §2

> **Apa yang berubah dari v2.**
>
> 1. **Mobile tidak diubah sama sekali.** Fase M dibuang, dan diganti fase D:
>    dokumentasi di `backend_presenly/docs/mobile-api.md`, supaya tim mobile bisa
>    menyusul kapan saja tanpa bergantung pada pekerjaan ini.
> 2. **Ditambahkan fase W (`web_presenly`)**, karena di situlah admin merekam
>    lembur manual dan atasan memutuskan, dan di situ penyaring per perusahaan
>    sudah ada sementara penyaring per lokasi belum.
> 3. **Payroll tetap tidak disentuh** (sama seperti v2), dan diganti §5: kontrak
>    data yang diuji.

---

## 0. Masalah, dan hasil yang diinginkan

Pengajuan lembur tidak memuat pilihan lokasi: klien mengirim tanggal, jam, jenis hari, dan keperluan, lalu server menentukan lokasinya dari **penempatan utama** pegawai, tanpa melihat tanggal. Pegawai yang hari itu bekerja di lokasi keduanya tetap tercatat di lokasi utama, dan cabang pada baris lembur di Odoo ikut salah.

Yang diinginkan:

1. Lokasi lembur mengikuti tempat kerja yang sebenarnya, dan bisa dinyatakan sendiri bila perlu.
2. Di Odoo, data lembur bisa disaring **per perusahaan dan per lokasi**, dan lengkap untuk digabungkan dengan `hr.employee` serta `hr.work.location`, sehingga payroll tinggal menariknya.

---

## 1. Fakta yang menentukan bentuk rencana

### Backend

| Fakta | Bukti | Artinya |
|---|---|---|
| Validasi tidak menerima lokasi | `src/validations/overtimeValidation.js` | Klien tidak bisa mengirimnya |
| Lokasinya dari penempatan utama, tanpa melihat tanggal | `OvertimeService.requestOvertime` → `resolvePrimaryLocation` | Sumber masalahnya |
| Sesi presensi menyimpan lokasi per tanggal | `AttendanceSession`: `user_id`, `work_date`, `location_id`, berindeks | Sumber yang benar sudah ada |
| Daftar lokasi yang boleh dipakai sudah ada endpoint-nya | `GET /api/employees/placements` → `listActiveLocationOptions` | Pilihan lokasi tinggal dipakai |
| Validator lokasi sudah ada | `hasActiveLocation(userId, locationId)` | Pilihan bisa diperiksa |
| Respons persetujuan sudah memuat `work_location_id` | `docs/mobile-api.md` §2.6 | Data itu sudah ada di jalur persetujuan |
| Laporan lembur menerima `month`, `year`, `status`, `client_id`, `project_id` | `OvertimeService` (laporan) | **Belum ada `location_id`**, padahal penyaring per lokasi dibutuhkan |
| Payload eksternal tidak membawa klien lokasi | `ExternalRawDataService.js`, pemetaan `overtimes` | Odoo menurunkannya; bisa dibuat pasti |
| Kolom `company_id` pada lembur sudah legacy | `EmployeeOvertime.js`, komentar "S5b" | Yang diekspor adalah klien **lokasinya** |

### Web

| Fakta | Bukti | Artinya |
|---|---|---|
| Ada form lembur manual, dan ia memanggil `/overtimes/manual` | `app/(authenticated)/shared/approvals/requests/_components/ManualOvertimeModal.tsx` | Admin merekam lembur dari sini, dan lokasinya sekarang ditentukan server |
| Laporan lembur sudah bisa disaring per klien dan proyek | `admin/attendance/overtime/page.tsx`: `clientFilter`, `projectFilter` | **Penyaring lokasi tinggal ditambahkan**, memakai filter backend yang baru |
| Kolom laporan sudah menampilkan "Tanggal & Lokasi" | `_components/overtime-columns.tsx` | Datanya sudah tampil, penyaringnya belum ada |
| Detail persetujuan belum menampilkan lokasi | `shared/approvals/requests/_components/OvertimeDetailModal.tsx` | Atasan memutuskan tanpa melihat di mana lembur terjadi |

### Odoo

| Fakta | Bukti | Artinya |
|---|---|---|
| Sudah ada kolom cabang dan lokasi | `tenant_client_company_id`, `tenant_client_id`, `location_id`, `location_name` | Separuh pekerjaan cermin sudah ada |
| Sudah ada penyaring grup perusahaan dan lokasi | view lembur: `group_internal_company`, `group_location` | Tinggal diperluas ke jenis lain |
| Payroll menyaring lembur lewat empat kunci | `presenly_payroll/.../custom_payroll_slip.py`: `hr_employee`, `status = approved`, rentang tanggal, `hr.work.location` | Inilah bentuk data yang harus bisa dijawab cermin (§5) |
| Dua relasi itu belum ada di cermin | mixin pengajuan hanya menyimpan id dan nama | Ditambahkan di fase O |

---

## 2. Keputusan yang dibutuhkan

| # | Pertanyaan | Rekomendasi |
|---|---|---|
| 1 | Urutan penentuan lokasi otomatis | Sesi presensi tanggal itu, lalu penempatan yang berlaku pada tanggal itu, lalu penempatan utama, lalu kosong |
| 2 | Pilihan lokasi oleh admin di web, wajib atau opsional | Opsional. Bawaan hasil penentuan otomatis, pilihannya dibatasi ke penempatan aktif pegawai itu |
| 3 | Berlaku untuk jenis pengajuan lain juga | Lembur dulu. Cuti dan surat sakit menyusul; koreksi presensi dan tukar shift belum bisa, payloadnya tidak membawa lokasi |

---

## 3. Fase pekerjaan

### Fase B: backend (`backend_presenly`)

| Kode | Isi | Berkas |
|---|---|---|
| B1 | `resolveLocationForDate(userId, date)`: sesi presensi tanggal itu, lalu penempatan yang berlaku tanggal itu, lalu penempatan utama, lalu null | `src/services/EmployeePlacementService.js` |
| B2 | Pengajuan menerima `work_location_id` **opsional**; diisi berarti diperiksa dengan `hasActiveLocation`, kosong berarti memakai B1 | `src/validations/overtimeValidation.js`, `src/services/OvertimeService.js` |
| B3 | Jalur sunting: lokasi mengikuti pilihan baru, atau ditentukan ulang bila tanggalnya berubah | idem |
| B4 | Jalur catatan manual admin: menerima lokasi opsional untuk pegawai yang dicatat, diperiksa terhadap penempatan pegawai itu | `src/controllers/overtimeController.js` |
| B5 | Laporan lembur menerima penyaring `location_id` | `src/services/OvertimeService.js` |
| B6 | Respons persetujuan dan detail menyertakan lokasi beserta kliennya | idem |
| B7 | Payload eksternal menyertakan klien **lokasi** (`location.internal_company`) | `src/services/ExternalRawDataService.js` |
| B8 | Opsional: isi lokasi baris lama dari sesi presensi tanggalnya, dengan hitungan lebih dulu | `src/scripts/` |

**Kriteria terima.** Mengisi lokasi kedua menyimpan baris dengan lokasi itu; mengosongkannya membuat lokasi mengikuti sesi presensi hari itu, lalu penempatan yang berlaku tanggal itu. Lokasi yang bukan milik pegawai ditolak dengan pesan jelas. Laporan bisa disaring per lokasi. Payload eksternal memuat klien lokasinya.

### Fase W: web (`web_presenly`)

| Kode | Isi | Berkas |
|---|---|---|
| W1 | Penyaring lokasi pada laporan lembur, bersanding dengan penyaring klien yang sudah ada | `admin/attendance/overtime/page.tsx` |
| W2 | Kolom lokasi pada laporan memakai data yang sama, dan ikut tampil saat penyaring aktif | `_components/overtime-columns.tsx` |
| W3 | Detail persetujuan menampilkan lokasi (dan kliennya) supaya atasan tahu di mana lembur terjadi | `shared/approvals/requests/_components/OvertimeDetailModal.tsx` |
| W4 | Form lembur manual: menampilkan lokasi yang akan dipakai, dan **opsional** bisa diganti dari daftar penempatan pegawai itu | `_components/ManualOvertimeModal.tsx` |

**Kriteria terima.** Laporan bisa disaring per perusahaan dan per lokasi secara bersamaan. Atasan melihat lokasi sebelum memutuskan. Form manual memperlihatkan lokasi yang akan tersimpan.

### Fase O: Odoo, cermin yang siap ditarik (`presenly_saas`, `presenly_saas_hr`)

Dibagi dua modul dengan sengaja: `presenly_saas` tidak boleh bergantung pada `hr`, sedangkan dua kolom di bawah menyentuh model native.

| Kode | Isi | Modul |
|---|---|---|
| O1 | Bila payload membawa klien lokasi, pakai itu; kalau tidak, tetap turunkan seperti sekarang | `presenly_saas` |
| O2 | `tenant_location_id` (many2one ke `presenly.saas.work.location`) supaya penyaringan per lokasi memakai relasi | `presenly_saas` |
| O3 | `hr_work_location_id` (ke `hr.work.location`) dan `hr_employee_id` (ke `hr.employee`), diisi dari id lokasi dan dari nopeg | `presenly_saas_hr` |
| O4 | Kolom dan penyaring grup perusahaan serta lokasi untuk empat jenis pengajuan lain | `presenly_saas` |
| O5 | Kontrak data payroll sebagai tes (§5) dan satu helper baca-saja opsional | `presenly_saas_hr` |
| O6 | Dokumentasi dan terjemahan | keduanya |

**Kriteria terima.** Memilih lokasi kedua membuat cabang baris itu = klien lokasi itu. Penyaring grup perusahaan dan lokasi bekerja di kelima daftar pengajuan. Baris lembur disetujui bisa dicari dengan empat kunci yang sama seperti payroll.

### Fase D: dokumentasi, bukan perubahan mobile

| Kode | Isi | Berkas |
|---|---|---|
| D1 | Bagian lembur: `work_location_id` opsional pada pengajuan dan penyuntingan, aturan penentuan otomatisnya, dan lokasi pada respons daftar serta detail | `backend_presenly/docs/mobile-api.md` §2.6 |
| D2 | Bagian pilihan lokasi: `GET /api/employees/placements` beserta bentuk jawabannya, supaya tim mobile bisa membuat pemilih lokasi bila nanti diperlukan | idem |
| D3 | Perubahan payload eksternal (klien lokasi) | `backend_presenly/docs/external-raw-api.md` |
| D4 | Arti kolom baru dan kontrak payroll | `presenly_saas/README.md` §4d |

**Kriteria terima.** Tim mobile bisa mengerjakan pemilih lokasinya hanya dari dokumen itu, tanpa membaca kode backend. Itu yang membuat keputusan "jangan ubah mobile" tidak menjadi utang yang tidak tercatat.

---

## 4. Urutan, dan alasannya

B1 dan B2 dulu, karena tanpa itu tidak ada lokasi yang bisa dikirim. Lalu B5, B6, dan B7, karena web menunggu penyaring laporan dan Odoo menunggu bentuk payload. Setelah itu W dan O boleh berjalan berbarengan, dan D ditulis saat B selesai (bukan di akhir), supaya tim mobile menerima kabarnya lebih awal.

---

## 5. Kontrak data untuk payroll (pengganti fase payroll)

Payroll menyaring lembur dengan empat kunci, di `presenly_payroll/models/custom_payroll_slip.py`:

```python
domain = [
    ('employee_id', '=', self.employee_id.id),   # hr.employee
    ('state', '=', 'approved'),
    ('date', '>=', start), ('date', '<=', end),
]
if self.work_location_id:
    domain.append(('work_location_id', '=', self.work_location_id.id))  # hr.work.location
```

Supaya penyambungannya nanti hanya mengganti nama model dan satu baris domain, cermin lembur harus bisa menjawab keempat kunci itu dengan arti yang sama:

| Kunci payroll | Padanannya di cermin | Keadaan |
|---|---|---|
| `employee_id` | `hr_employee_id` (O3), diisi dari nopeg | **belum ada** |
| `state = approved` | `status = approved` (`status_raw` menyimpan nilai asli) | sudah ada |
| rentang `date` | `overtime_date`, berindeks | sudah ada |
| `work_location_id` | `hr_work_location_id` (O3), diisi dari `location_id` lewat `hr.work.location.presenly_external_id` | **belum ada** |
| cabang pembayar | `tenant_client_company_id` | sudah ada |

Yang **tidak** dikerjakan, dan itu disengaja: pemilihan pegawai per cabang di wizard, aturan gaji per cabang, dan kolom pada batch serta slip. Itu sisi payroll, dan payroll belum terpasang di basis data ini.

Buktinya tes, bukan klaim: satu tes mencari lembur disetujui untuk satu pegawai, satu lokasi, dan satu periode dengan keempat kunci itu, lalu membandingkannya dengan pencarian lewat relasi baru.

---

## 6. Uji silang yang wajib ada

1. **Lokasi lembur melawan sesi presensi.** Untuk lembur hari kerja, lokasi baris lembur sama dengan lokasi sesi presensi hari itu.
2. **Cabang melawan lokasi.** `tenant_client_company_id` sama dengan klien dari `tenant_location_id`.
3. **Empat kunci payroll** mengembalikan baris yang benar.
4. **Aturan isolasi tetap utuh.** Pengguna cabang tidak melihat cabang lain; pengelola tidak melihat tenant lain.
5. **Penyaring laporan.** Menyaring per klien dan per lokasi bersamaan menghasilkan himpunan yang benar, bukan gabungan keduanya.

---

## 7. Risiko, dan mitigasinya

| Risiko | Mitigasi |
|---|---|
| Validasi baru menolak pengajuan lama | Lokasinya opsional; yang lama tetap sah |
| Lembur dipindahkan ke cabang lain | Pilihan dibatasi ke penempatan aktif; atasan melihat lokasinya; perubahannya tercatat |
| Baris lama tanpa lokasi | Dibiarkan kosong, hanya terlihat HR dan pengelola; B8 opsional mengisinya dari sesi presensi dengan hitungan lebih dulu |
| Web dan backend tidak sinkron | W dikerjakan setelah B5 ada, dan penyaring lokasi memakai filter yang sama dengan yang diuji di backend |
| Mobile tertinggal | D ditulis begitu B selesai, dan berisi contoh permintaan serta jawaban, bukan sekadar daftar field |
| Data siap tetapi payroll belum ada | Memang begitu keadaannya; kontraknya diuji (§5) supaya hasilnya bisa diperiksa tanpa payroll |

---

## 8. Yang sengaja tidak dikerjakan

- **Tidak mengubah mobile sama sekali.** Perubahan untuk mobile hanya ditulis di `docs/mobile-api.md`.
- **Tidak menyentuh `hr_payroll_custom`**, termasuk wizard, mesin aturan gaji, dan tampilannya.
- Tidak mengubah alur absen di mobile.
- Tidak memindahkan pegawai antar perusahaan.
- Tidak membuang kolom legacy di server.
- Tidak mengubah aturan isolasi cabang yang sudah ada.
- Tidak menjadikan lokasi wajib saat mengajukan lembur.

---

## 9. Keadaan data sekarang, sebagai titik tolak

Di Odoo: 4 baris lembur, semuanya di CLIENT 2 dengan lokasi `PT KONSULTA SEMEN GRESIK`; 3 cuti dan 3 surat sakit sudah bercabang. `yusril` punya CLIENT 1 dan CLIENT 2, `feri` punya CLIENT 2.

Modul payroll (`hr_payroll_custom`, `presenly_payroll`) **belum terpasang**, dan tabel `custom_payroll_batch` belum ada. Pemisahan yang sebenarnya baru terlihat setelah ada lembur di cabang kedua, jadi data ujinya harus dibuat, bukan ditunggu.

---

## 10. Keadaan pelaksanaan (diperbarui setelah eksekusi)

Bagian ini menggantikan "rencana" untuk hal-hal yang sudah dikerjakan; sisanya tetap
rencana.

| Fase | Butir | Keadaan |
|---|---|---|
| B | B1 `resolveLocationForDate` | **Selesai** |
| B | B2 `work_location_id` opsional di pengajuan dan penyuntingan | **Selesai**, pilihan divalidasi ke penempatan aktif (400 bila bukan) |
| B | B3 lokasi dihitung ulang hanya bila tanggalnya berubah | **Selesai** |
| B | B4 lembur manual (dibuat admin) menerima lokasi | **Selesai** |
| B | B5 laporan menerima penyaring `location_id` | **Selesai** |
| B | B6 respons persetujuan, laporan, dan daftar aplikasi memuat lokasinya | **Selesai** (`workLocation`, beserta `tenantClient`) |
| B | B7 payload eksternal memuat klien lokasinya | **Selesai** (`location.internal_company`, juga pada surat sakit) |
| B | B8 pengisian lokasi untuk baris lama | **Tidak dikerjakan** (lihat catatan di bawah) |
| W | W1 penyaring lokasi di laporan lembur | **Selesai** |
| W | W2 ekspor mengikuti penyaringnya | **Selesai** |
| W | W3 lokasi dan cabang tampil di rincian persetujuan | **Selesai** |
| W | W4 pemilih lokasi di formulir lembur manual | **Belum** |
| O | O1 klien lokasi dari payload dipakai lebih dulu | **Selesai** |
| O | O2 `tenant_location_id` | **Selesai** |
| O | O3 `hr_work_location_id` dan `hr_employee_id` | **Selesai** |
| O | O4 kolom serta penyaring di daftar kelima jenis pengajuan | **Selesai** |
| O | O5 uji kesiapan payroll | **Selesai** (5 uji) |
| D | D1-D3 dokumentasi API mobile dan API eksternal | **Selesai** |
| D | D4 catatan Odoo | **Selesai** |

Yang **tidak** dikerjakan, dan sebabnya:

- **B8** — baris lama tidak diisi ulang otomatis. Lokasi baris lama hanya bisa
  ditebak dari penempatan atau sesi presensi saat itu, dan tebakan yang salah lebih
  berbahaya daripada kolom kosong: payroll akan menagihnya tanpa ada yang menyadari.
  Baris baru sudah benar sejak awal.
- **W4** — formulir lembur manual (dibuat admin) belum punya pemilih lokasi; yang
  dikirim adalah lokasi hasil perhitungan server. Endpointnya sendiri sudah menerima
  `work_location_id`.
- **Mobile** — tidak disentuh sama sekali, sesuai keputusan. Yang berubah hanya
  dokumentasinya.
- **Payroll** — tidak disentuh sama sekali. Yang disiapkan hanya datanya, dan
  kontraknya diuji di Odoo.
