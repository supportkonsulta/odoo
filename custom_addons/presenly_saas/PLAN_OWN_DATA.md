# Rencana: data milik sendiri, dan label proyek yang masih JSON mentah

Dua hal, satu akar: cermin presensi di Odoo. Yang pertama adalah kolom yang salah
diisi, yang kedua adalah tidak adanya pagar sehingga data itu tidak bisa dipakai
oleh orang yang seharusnya melihatnya: pegawainya sendiri.

---

## 0. Masalah

**M1. Kolom Project berisi JSON mentah.** Di form Detail Data Presensi, kolom
Project menampilkan dict apa adanya:

```
{'id': 3, 'project_name': 'MAMBU KECUT', 'project_code': '987364',
 'client': {'id': 1, 'name': 'CLIENT 1'}}
```

Sebabnya satu baris di
`custom_addons/presenly_saas/models/presenly_saas_attendance_log.py:435`:

```python
'project_name': employee.get('project') or False,
```

`employee.project` dari API berbentuk objek, sedangkan `project_name` adalah
`fields.Char`. Odoo menyimpan repr-nya, dan yang terlihat di layar adalah repr itu.
Baris yang sudah ada ikut rusak: di basis `odoo` ada 7 baris cermin presensi dan
**semuanya** berisi repr seperti di atas.

**M2. Pengguna selain pengelola tidak bisa melihat datanya sendiri.** Tiga sebab,
dan ketiganya harus dibetulkan bersama supaya hasilnya benar:

| Sebab | Bukti |
|---|---|
| Menu akar Presenly SaaS hanya untuk Manager | `views/presenly_saas_menus.xml:21` (`groups="presenly_saas.group_presenly_saas_manager"`), jadi pengguna biasa tidak melihat menu apa pun |
| Cermin presensi **tidak punya aturan akses sama sekali** | tidak ada satu pun `ir.rule` untuk `presenly.saas.attendance.log`; ACL-nya memberi `base.group_user` hak baca (`security/ir.model.access.csv:34`) |
| Pengajuan memakai aturan **cabang**, bukan milik sendiri | `security/presenly_saas_security.xml:69` dan seterusnya: `base.group_user` melihat semua baris yang perusahaannya ada di `company_ids`, artinya rekan sekantor ikut terlihat |

Akibat dari sebab kedua perlu ditegaskan: Odoo 19 **tidak** menambahkan saringan
perusahaan sendiri. Di `odoo/addons/base/models/ir_rule.py:41-50`, `company_ids`
hanya variabel yang bisa dipakai di domain, bukan aturan yang dipasang otomatis.
Jadi model dengan `company_id` tanpa aturan akan menampilkan baris dari semua
perusahaan bagi pengguna internal mana pun yang membukanya.

---

## 1. Fakta yang menentukan bentuk rencana

| Fakta | Berkas |
|---|---|
| Kolom proyek hanya ada di form, tidak di daftar | `views/presenly_saas_attendance_views.xml:198` (form), daftar di baris 10-31 tidak memuatnya |
| Cermin lokasi dan timesheet sudah memakai pola `isinstance(dict)` untuk proyek | `models/presenly_saas_reference_mirrors.py:55`, `models/presenly_saas_timesheet_mirrors.py:177` |
| Cermin proyek sudah ada dan bisa jadi relasi | `models/presenly_saas_timesheet_mirrors.py:50` (`presenly.saas.project`, `project_code` + `project_name` wajib) |
| Cara mengetahui "milik sendiri" sudah dipakai modul ini | `models/presenly_saas_approval_hr.py:178`: `self.env.user.employee_id.presenly_nopeg` |
| `res.users.employee_id` adalah pegawai **pada perusahaan yang sedang aktif** | `addons/hr/models/res_users.py:63-64` (`employee_ids` difilter perusahaan aktif, `employee_id` dihitung per perusahaan)  -  jadi aturan yang memakainya akan buta bagi pegawai yang record-nya ada di perusahaan lain |
| Aturan yang menyentuh `hr` harus tinggal di `presenly_saas_hr` | aturan timpa SaaS di `presenly_saas_hr/security/presenly_saas_submission_rules.xml`; `presenly_saas` dilarang bergantung pada `hr` |
| Pola membuka menu akar lalu mengunci anaknya sudah ada | `presenly_saas_hr/security/presenly_saas_approver.xml` (komentar panjang di atas `group_presenly_saas_approver`) |
| Menu akar, `Attendance`, dan `Requests` terkunci ke Manager | `views/presenly_saas_menus.xml:21`, `:36`, `:56`; `Subscription`, `Reference`, `Timesheet`, dan `Sync Log` juga terkunci di berkas yang sama |
| Indeks untuk `employee_nopeg` belum ada | `models/presenly_saas_attendance_log.py:48` |
| Migrasi memakai helper yang sama dengan penarikan | `migrations/19.0.2.4.0/post-migrate.py` memanggil `_mirror_fill_branches` |
| Web sudah memakai endpoint milik sendiri | `web_presenly/app/(authenticated)/employee/attendance/history/page.tsx:118` memanggil `/attendance/me/web`, yang di backend memang `listMineWeb` (`backend_presenly/src/routes/attendanceRoutes.js:38`) |

---

## 2. Keputusan yang dibutuhkan

1. **Lingkup.** Odoo saja (rekomendasi), atau termasuk web? Bacaan saya: Odoo,
   karena kerusakan JSON-nya terbukti di basis Odoo, sedangkan web sudah memakai
   endpoint milik sendiri (`/attendance/me/web`, riwayat lembur pegawai). Bagian 7
   menuliskan apa yang akan diperiksa bila ternyata yang dimaksud web.
2. **Pengguna biasa melihat miliknya saja.** Rekomendasi: ya, dan aturan cabang
   untuk `base.group_user` dipindahkan ke grup Approver **lewat modul HR**, supaya
   pemasangan tanpa HR tidak berubah perilakunya (tetap seperti sekarang).
3. **Pengelola melihat lintas perusahaan yang ia boleh.** Rekomendasi: ya,
   `company_id in company_ids` untuk cermin presensi, karena itulah pagar tenant.
4. **Kolom proyek.** Rekomendasi: betulkan kolomnya (`project_code` +
   `project_name`) sekarang, dan tambahkan relasi ke `presenly.saas.project`
   sebagai pekerjaan lanjutan bila memang perlu menyaring/mengelompokkan per
   proyek. Relasi itu ditulis `store=False` seperti `work_location_id` sekarang,
   jadi harus dibuat `search` sendiri bila mau dipakai di aturan atau group by.
5. **Menu untuk pengguna biasa.** Rekomendasi: tidak perlu menu baru. Cukup buka
   menu akar untuk `base.group_user`, kunci anak yang sensitif (Subscription,
   Timesheet, Sync Log, Reference), karena aturan aksesnya sudah membuat daftar
   yang ada menampilkan hanya baris miliknya.
6. **Pengguna tanpa pegawai tertaut.** Rekomendasi: tidak melihat apa pun, dan
   jumlahnya dilaporkan. Melihat rekan sekantor lebih merugikan daripada melihat
   kosong: yang salah tidak terlihat, yang kosong ketahuan.

---

## 3. Fase pekerjaan

### Fase A: label proyek berhenti menampilkan JSON mentah (`presenly_saas`)

| Langkah | Isi |
|---|---|
| A1 | `_mirror_values` mengambil `project` hanya bila dict, lalu menulis `project_code` dan `project_name`. Nama diambil dari `project_name` dengan `name` sebagai cadangan, karena resource lokasi memakai `name` sedangkan pegawai memakai `project_name` |
| A2 | Field baru `project_code` (Char). Bila proyeknya berbentuk string, kolomnya dibiarkan **kosong** dan kejadiannya dicatat di log: menebak isi string berarti menampilkan JSON mentah dengan cara lain |
| A3 | Daftar dan form menampilkan `[KODE] Nama` pada satu kolom, plus group by per proyek di search view |
| A4 | Audit pola serupa di semua cermin (`grep` untuk nilai `dict` yang masuk ke `Char`). Hari ini hanya kolom ini yang salah; hasil audit ditulis di ringkasan pekerjaan |

### Fase B: membetulkan baris yang sudah ada (migrasi `19.0.2.5.0`)

| Langkah | Isi |
|---|---|
| B1 | `post-migrate.py` membaca `raw_payload.employee.project`, lalu menulis ulang `project_name` dan `project_code`. Idempotent: yang sudah bersih tidak disentuh |
| B2 | Hanya baris yang kolomnya masih berbentuk repr yang diperbaiki (penanda: nilainya dimulai `{`), supaya nama proyek yang sudah disunting orang tidak tertimpa |
| B3 | Jumlah yang diperbaiki dan yang payload-nya tidak memuat proyek dicatat di log, seperti migrasi sebelumnya |

### Fase C: setiap pengguna melihat datanya sendiri

| Langkah | Modul | Isi |
|---|---|---|
| C1 | `presenly_saas` | Aturan pengelola untuk cermin presensi: `[('company_id', 'in', company_ids)]` untuk `group_presenly_saas_manager`. **Hari ini tidak ada aturan apa pun**, jadi ini sekaligus menutup kebocoran lintas perusahaan |
| C1b | `presenly_saas` | Pagar dasar untuk `base.group_user` pada cermin presensi: `[('company_id', 'in', company_ids)]`. Ini bukan pembatas yang diinginkan, melainkan jaring bila `presenly_saas_hr` tidak terpasang: tanpa HR, tidak ada cara mengenali "milik sendiri" |
| C2 | `presenly_saas_hr` | Kolom `presenly_nopeg` pada `res.users`, dihitung dari `employee_ids.presenly_nopeg`. Dibuat karena `employee_id` hanya melihat pegawai di perusahaan yang sedang aktif (`addons/hr/models/res_users.py:63-64`), sedangkan record pegawai di sini berada di perusahaan integrasi. Tanpa kolom ini, pegawai yang sedang bekerja di perusahaan cabang akan kehilangan pandangannya sendiri |
| C2b | `presenly_saas_hr` | Aturan "milik sendiri" untuk cermin presensi: `[('employee_nopeg', '=', user.presenly_nopeg or '__tanpa_nopeg__')]`. Sentinel dipakai supaya pengguna tanpa nopeg melihat nol baris, bukan baris yang nopeg-nya kosong |
| C3 | `presenly_saas_hr` | Aturan "milik sendiri" untuk kelima model pengajuan: `[('hr_employee_id.presenly_nopeg', '=', user.presenly_nopeg or '__tanpa_nopeg__')]`. Lewat nopeg, bukan id pegawai, karena tautan pengajuan ke pegawai memang dicocokkan per nopeg |
| C4 | `presenly_saas_hr` | Kelima aturan cabang pengajuan **dan** pagar dasar cermin presensi (C1b) diperbarui: `base.group_user` **dikeluarkan**, grup Approver **ditambahkan** (`eval="[(3, ref('base.group_user')), (4, ref('group_presenly_saas_approver'))]"`). Dengan begitu persetujuan tetap melihat satu cabang, pegawai biasa hanya melihat miliknya, dan pemasangan tanpa HR tetap seperti sekarang |
| C5 | `presenly_saas` | Menu akar, `Attendance`, dan `Requests` dibuka untuk `base.group_user`; anak yang tidak boleh terlihat tetap dikunci ke Manager: `Monitoring` (isinya lintas pegawai), `Subscription`, `Reference`, `Timesheet`, dan `Sync Log`. `Reference` dan `Subscription` sudah terkunci, jadi yang berubah hanya `Monitoring` |
| C6 | `presenly_saas` | Indeks untuk `employee_nopeg`, karena aturan C2b menyaring dengan kolom itu |
| C7 | keduanya | `i18n/id.po`: label kolom `project_code`, penyaring group by proyek, dan nama menu yang berubah kepemilikannya |

Aturan yang perlu diingat saat menulis C2b sampai C4: aturan **grup** digabung
dengan OR, sedangkan aturan **global** digabung dengan AND. Artinya menambah aturan
"milik sendiri" untuk `base.group_user` **tanpa** mengeluarkan grup itu dari aturan
cabang tidak akan mengubah apa pun: pengguna biasa tetap melihat satu cabang.
Manager dan HR tidak kehilangan apa pun, karena aturan mereka tetap berlaku dan
hasilnya digabung.

### Fase D: dokumentasi

| Langkah | Isi |
|---|---|
| D1 | `presenly_saas/README.md`: bagian baru tentang siapa melihat apa, termasuk alasan cermin presensi akhirnya punya aturan perusahaan |
| D2 | `presenly_saas_hr/README.md`: bagian tentang data milik sendiri, dan kenapa aturan itu tinggal di modul HR (butuh `user.employee_id`) |
| D3 | Bagian keadaan pelaksanaan di berkas ini, diisi setelah pekerjaan selesai |

---

## 4. Uji yang wajib ada

| Uji | Yang dibuktikan |
|---|---|
| Payload dengan `project` berbentuk objek | `project_name` dan `project_code` terisi, dan **tidak** ada tanda `{` di kolomnya |
| Payload tanpa `project`, dan payload dengan `project` berbentuk string | Kolom kosong, tidak ada galat |
| Migrasi dari baris berisi repr | Baris lama diperbaiki, baris yang sudah bersih tidak disentuh, dijalankan dua kali hasilnya sama |
| Pengguna dengan nopeg A membuka daftar presensi | Hanya melihat baris nopeg A, termasuk saat ada baris dari perusahaan lain |
| Pengguna yang sama membuka kelima daftar pengajuan | Hanya melihat pengajuannya sendiri |
| Approver | Tetap melihat satu cabang |
| Manager dan HR | Tidak kehilangan pandangan sebelumnya |
| `res.users.presenly_nopeg` saat pegawainya di perusahaan lain dari perusahaan aktif pengguna | Tetap terisi, dan aturan tetap menunjukkan data miliknya |
| Pengguna tanpa pegawai tertaut, dan pengguna tanpa nopeg | Melihat nol baris, bukan semuanya |
| Pemasangan tanpa `presenly_saas_hr` | Diperiksa manual, karena suite uji berjalan dengan HR terpasang: tanpa HR, `base.group_user` harus tetap terpagar perusahaan |

---

## 5. Risiko dan mitigasi

| Risiko | Mitigasi |
|---|---|
| Mengeluarkan `base.group_user` dari aturan cabang membuat rekan sekerja tidak lagi terlihat | Memang tujuannya. Approver tetap melihat cabang, dan itu diuji |
| Baris yang tautan pegawainya belum terisi tidak terlihat oleh pemiliknya | Pengisian tautan berjalan tiap tarikan; jumlah baris tanpa tautan dicatat di log, dan HR tetap melihat semuanya |
| Nopeg berubah atau dihapus di aplikasi | Aturan dinilai saat dibaca, jadi kehilangan nopeg langsung mencabut pandangan. Berbeda dengan akses perusahaan yang memang tidak pernah dicabut |
| Kolom `res.users.presenly_nopeg` tidak ikut terhitung ulang saat `hr.employee.presenly_nopeg` berubah | Ketergantungan ditulis eksplisit (`@api.depends('employee_ids.presenly_nopeg')`) dan diuji dengan mengubah nopeg pegawai lalu membaca ulang kolomnya |
| Nama proyek yang sudah disunting orang tertimpa migrasi | Migrasi hanya menyentuh nilai yang masih berbentuk repr |
| Aturan baru memperlambat daftar | Satu indeks pada `employee_nopeg`; traversal `hr_employee_id.presenly_nopeg` menjadi join biasa |

---

## 6. Yang sengaja tidak dikerjakan

- Tidak menyentuh payroll, mobile, dan web (kecuali keputusan 1 mengubahnya).
- Tidak memberi hak tulis kepada pengguna biasa: cermin tetap hanya baca.
- Tidak membuat model baru untuk "presensi saya": aturan akses sudah cukup.
- Tidak mencabut tautan pegawai yang sudah ada, dan tidak mengubah aturan cabang
  untuk Manager.
- Tidak memperbaiki cermin lain yang punya proyek (lokasi, timesheet) karena
  keduanya sudah benar; hanya hasil auditnya yang dilaporkan.

---

## 7. Bila yang dimaksud ternyata web

Bila M2 dimaksudkan pada web, bukan Odoo, rancangannya berbeda dan lebih kecil:
halaman pegawai sudah memanggil endpoint milik sendiri (`/attendance/me/web`,
riwayat lembur pegawai), jadi yang perlu diperiksa adalah halaman detail dan
daftar yang dipakai peran lain (mis. `shared/approvals`) apakah memakai endpoint
"milik sendiri" atau endpoint admin, dan apakah label proyek di modal detail
membaca objek proyek atau string. Bagian 1 sudah memuat bukti bahwa jalur Odoo
yang rusak, jadi keputusan 1 menentukan mana yang dikerjakan lebih dulu.

---

## 8. Keadaan data sekarang, sebagai titik tolak

- Basis `odoo`: 7 baris cermin presensi, **semuanya** berisi repr proyek. Tidak
  ada satu pun yang sudah bersih, jadi migrasi Fase B akan menyentuh ketujuhnya.
- Cermin pengajuan: 4 lembur, 3 cuti, 3 surat sakit, semuanya sudah bercabang.
- `res.users` belum punya kolom Presenly apa pun, dan tidak akan ditambahkan:
  nopeg dibaca lewat `user.employee_id.presenly_nopeg` seperti yang sudah dipakai
  tombol keputusan persetujuan.

---

## 9. Keadaan pelaksanaan

Dikerjakan sesuai keputusan: keenam butir §2 disetujui apa adanya.

| Butir | Keadaan |
|---|---|
| A1-A4 pemisahan kode dan nama proyek, label `[KODE] Nama`, group by | **Selesai** |
| B1-B3 migrasi `19.0.2.5.0` | **Selesai**, dan dibuktikan dengan menjalankannya sungguhan: satu baris rusak disiapkan di basis uji, migrasi melaporkan "1 baris diperbaiki, 0 dikosongkan", dan kolomnya menjadi `987364` + `MAMBU KECUT` |
| C1 pagar perusahaan untuk pengelola | **Selesai** |
| C1b pagar dasar untuk pemasangan tanpa HR | **Selesai** (dipindahkan ke Approver oleh HR) |
| C2 kolom `res.users.presenly_nopeg` | **Selesai** |
| C2b, C3 aturan "milik sendiri" | **Selesai** (1 cermin presensi + 5 pengajuan) |
| C4 aturan cabang diserahkan ke Approver | **Selesai** |
| C5 menu untuk pengguna internal, Monitoring dikunci | **Selesai** di kedua modul |
| C6 indeks `employee_nopeg` | **Selesai** |
| C7 `i18n/id.po` | **Selesai** (label sudah ada; rujukan kolom baru ditambahkan) |
| D1, D2 catatan di kedua README | **Selesai** |

Yang **berubah dari rencana**, dan sebabnya:

- **Aturan "milik sendiri" tidak berpagar perusahaan.** Rencananya memasang
  `company_id in company_ids` di situ. Setelah diperiksa pada data nyata, pagar itu
  justru merusak: pengguna cabang tidak punya perusahaan integrasi di daftar
  perusahaannya (`yusril` hanya punya CLIENT 1 dan CLIENT 2), sedangkan seluruh
  baris cermin berada di perusahaan integrasi. Pagar itu membuat pegawai cabang
  kehilangan datanya sendiri. Batas tenant tetap dijaga aturan pengelola, Approver,
  dan HR, ditambah awalan tenant pada nopeg. Ada tes yang menjaga keputusan ini.
- **Aturan HR untuk cermin presensi ditambahkan** (tidak ada di rencana awal).
  Tanpa itu, pengguna HR kehilangan pandangan yang sebelumnya ia punya, karena
  aturan lama memang tidak ada dan aturan barunya hanya untuk pemilik datanya.
- **Label proyek memakai kolom terhitung** `project_label`, bukan dua kolom
  terpisah, supaya bentuknya satu kolom seperti yang diminta.

Lanjutan yang dikerjakan setelahnya:

- **Relasi cermin presensi ke `presenly.saas.project`** (keputusan 4) sempat
  dibuat di versi `19.0.2.6.0`, lalu **dibatalkan atas permintaan pemilik data**
  dan dibuang di `19.0.2.7.0`. Alasannya masuk akal: kode dan nama proyeknya sudah
  tersimpan di barisnya sendiri, jadi kolom relasinya hanya menggandakan kolom yang
  sama di layar - pemiliknya melihatnya sebagai dua kolom proyek, bukan satu.
  Cermin proyeknya sendiri tetap dipakai halaman Projects dan tarikan data
  referensi; yang dibuang hanya tautannya dari log presensi. Migrasi 19.0.2.6.0
  dihapus (belum sampai ke basis siapa pun kecuali basis uji), dan kolom yang
  sempat dibuat dibuang 19.0.2.7.0 supaya tidak tertinggal sebagai kolom mati.
  Uji relasinya ikut dibuang; yang tetap ada uji pemisahan kode dan nama.
- **Pemasangan tanpa `presenly_saas_hr` dicoba sungguhan**: basis bersih berisi
  `presenly_saas` saja, seluruh suite-nya dijalankan di sana. **371 uji, 0 gagal.**
  Dua uji lama ternyata menganggap `presenly_saas_hr` selalu terpasang, dan
  keduanya diperbaiki: satu melewati cermin yang modulnya tidak ada, satu lagi
  melewati diri bila modul HR tidak terpasang. Sebuah uji baru memastikan pagar
  perusahaan pada cermin presensi ada di kedua konfigurasi, dan bahwa pengelola
  tetap melihat perusahaannya.
- Peringatan Odoo "dua kolom berlabel sama" pada kolom proyek dihapus dengan
  membedakan label `project_name`; satu peringatan serupa yang sudah ada
  sebelumnya pada cermin jadwal (`schedule_id` berlabel "Day") ikut dibetulkan.

Yang **belum**:

- Basis `odoo` perlu dinaikkan versinya (`-u presenly_saas,presenly_saas_hr`) agar
  kolom dan aturannya berlaku, dan ketujuh baris proyek yang rusak diperbaiki
  migrasinya. Selama itu belum, layarnya masih menampilkan repr.
