# Plan: Penegakan Guard Langganan Secara Global

**Addon:** `custom_addons/presenly_saas`
**Platform:** Odoo 19.0
**Versi dokumen:** DRAFT v1 + catatan as-built (§16)
**Status:** F1, F2, dan bagian F4 (akses sementara) **selesai dikerjakan dan diuji**.
F3 tidak diperlukan karena scope yang dipilih adalah penutupan penuh. F5 (kunci tulis
ORM) tidak diambil. Keputusan pemilik: scope **A**, fail-closed setelah tenggang,
per **perusahaan aktif**, API aplikasi ditutup dan webhook dibiarkan hidup.
**antislop:** DURING (halaman blokir diperlakukan sebagai pekerjaan UI, lihat §6)

---

## 0. Masalah

Hari ini `Mode Penegakan = Wajibkan` **tidak menutup akses apa pun**. Ia hanya
membuat API guard menjawab "diblokir", dan tidak ada satu pun pemanggil di kode
produksi:

| Fakta | Bukti |
|---|---|
| API-nya ada dan sudah lengkap | `models/presenly_saas_guard.py:79` (`is_allowed`), `:90` (`check`), `:107` (`has_feature`) |
| Tidak ada pemanggil di produksi | grep `is_allowed(` / `has_feature(` / `saas.guard` di seluruh `custom_addons`: hanya `tests/test_guard_contract.py` dan `tests/test_plan_features.py` |
| Keputusan blokir ada di satu tempat | `models/presenly_saas_subscription.py:304` `_effective_state()` |
| Bawaannya `warn`, bukan `enforce` | `models/presenly_saas_config.py:196` |
| Penyegaran harian + manual | cron `Presenly SaaS: Refresh Subscription` (`data/ir_cron_data.xml`), `action_refresh_subscription` (`models/presenly_saas_config.py:358`), `_cron_refresh_all` (`:1381`) |
| `Masa Tenggang` tidak dipakai di jalur penegakan | `_grace_expired` (`:325`) hanya dipakai `_banner_severity` (`:329`); tesnya justru menegaskan snapshot `cached` tetap lolos setelah 60 hari (`tests/test_guard_contract.py:118`) |

Jadi yang diminta dokumen ini adalah: **memindahkan penegakan dari kontrak
per-pemanggil menjadi gerbang di jalur masuk**, supaya langganan yang hangus
menutup akses tanpa bergantung pada kerelaan modul lain.

---

## 1. Temuan yang menentukan bentuk rencana

### 1.1 Tidak ada "aplikasi Presenly" yang bisa disembunyikan

`presenly` menumpang aplikasi native, jadi "blokir modul Presenly" bukan operasi
yang jelas batasnya:

| Fakta | Bukti |
|---|---|
| Menu root Presenly **nonaktif**, jadi tidak ada app Presenly di home | `custom_addons/presenly/views/presenly_menus.xml:55` (`active="False"`) |
| UI-nya hidup di dalam aplikasi native | `presenly/views/hr_attendance_integration_views.xml`, `hr_employee_integration_views.xml`, `hr_leave_report_calendar_views.xml`, `hr_attendance_presenly_actions.xml` |
| Antrean persetujuan memakai model native | `hr_attendance_presenly_actions.xml`: `res_model = hr.leave`, `model_id ref="hr_holidays.model_hr_leave"` |
| Presenly bahkan menyembunyikan setelan native | `hr_attendance_integration_views.xml:288` dan `:303` (blok overtime dan kiosk) |

Akibatnya: menyembunyikan menu tidak memblokir apa pun. Yang bisa diblokir
adalah **model** (`presenly.*`), **action** milik modul Presenly, dan **API**
`/api/presenly/v1/*`; sedangkan data yang sudah dicerminkan ke `hr.employee`,
`hr.attendance`, `hr.leave` tetap milik aplikasi native. Ini yang membuat §2
harus dipilih sadar.

### 1.2 Batasan arsitektur harus dibalik, seperti §1.2b dulu

`PLAN.md` §1.2 dan §1.3 menulis: tanpa dependensi bisnis native, **tanpa
penegakan otomatis** di titik check-in / pengajuan / cuti / lembur, dan tidak
memakai `ir.config_parameter` sebagai penyimpanan. Gerbang global menuntut
kebalikannya:

| Yang dituntut | Dipakai untuk | Status batasan |
|---|---|---|
| `ir.http` (infrastruktur native) | satu gerbang di jalur masuk semua rute | dibalik, sadar |
| `ir.ui.menu` (bila scope data dipilih) | konsistensi navigasi | dibalik, sadar |
| satu `ir.config_parameter` | kill switch darurat saat insiden | dibalik, sadar, hanya satu kunci |

Yang **tetap** berlaku dan tidak dibatalkan:

- **Nol berkas** di `custom_addons/presenly` disentuh.
- Tidak mewarisi model bisnis native. Yang di-inherit hanya `ir.http` dan
  `ir.ui.menu`, yaitu infrastruktur, bukan model bisnis.
- Setelan tetap disimpan di `presenly.saas.config`. ICP hanya untuk kill switch.

Pembalikan ini ditulis di `PLAN.md` dengan pola yang sama seperti §1.2b, supaya
tidak jadi "batasan yang hilang diam-diam".

---

## 2. Keputusan 1: apa arti "tidak ada akses"

| Opsi | Yang benar-benar terjadi | Bisa diwujudkan | Catatan |
|---|---|---|---|
| **A. Backend penuh** | Semua rute backend untuk pengguna internal tenant ditolak, kecuali allowlist. Situs publik, portal, login, dan halaman blokir tetap hidup | Ya, satu gerbang | Tenant tidak bisa memakai Odoo sama sekali sampai bayar. Perlu persetujuan komersial. Pemutakhiran modul dari UI ikut mati (ada jalur CLI, §8) |
| **B. Hanya milik Presenly** | `presenly.*`, action milik modul Presenly, dan `/api/presenly/v1/*` ditolak; aplikasi native tetap | Ya | **Bocor**: absensi, cuti, dan pegawai tetap bisa dibaca dan disunting lewat aplikasi native, padahal itu isi produknya. Sulit dijelaskan ke pelanggan |
| **C. Kunci data** | Tulis ke model yang diisi Presenly ditolak, baca tetap boleh | Ya, lewat lapisan ORM | Lembut, tidak "tidak ada akses". Butuh daftar model yang tepat dan dirawat |

**Rekomendasi: A**, karena itu arti harfiah dari permintaan ("hangus berarti
tidak ada akses"), karena ia satu gerbang yang mudah diuji, dan karena C bisa
menyusul tanpa membongkar apa pun: fungsi keputusan sudah mengembalikan
keadaan, gerbangnya hanya memetakan keadaan ke izin.

B tidak dibangun. Ia menjual rasa aman yang tidak ada.

---

## 3. Arsitektur: satu fungsi keputusan, empat lapisan

| Lapis | Berkas | Menangkap | Biaya |
|---|---|---|---|
| 1. Jalur masuk | `models/ir_http.py` (`_inherit = 'ir.http'`, override `_pre_dispatch`) | seluruh webclient, `/web/dataset/call_kw`, `/jsonrpc` dengan API key, laporan PDF/XLSX, API mobile | satu cek cache per permintaan |
| 2. Navigasi | `models/ir_ui_menu.py` (override `_visible_menu_ids`, `odoo/addons/base/models/ir_ui_menu.py:75`) | daftar menu yang dikirim `load_menus` (`addons/web/controllers/home.py:85`) | satu filter per boot |
| 3. ORM (opsional, F5) | hook di `models.Model` lewat `_register_hook` | cron, server action, impor, `shell`, XML-RPC langsung ke model | per operasi ORM |
| 4. Tampilan | `controllers/blocked.py` + `views/*.xml` | penjelasan ke pengguna | nol |

Lapis 1 dipilih karena `_pre_dispatch` (`odoo/addons/base/models/ir_http.py:298`)
sudah berjalan **setelah autentikasi** (jadi uid dan company diketahui) dan
**sebelum controller** (jadi tidak ada efek samping yang perlu dibatalkan). Satu
tempat itu menutup semua jenis rute, termasuk `/web/dataset/call_kw` yang
`type='jsonrpc'` (`addons/web/controllers/dataset.py:28`, `model` tersedia di
`args`), dan API mobile `/api/presenly/v1/*` yang juga `type='jsonrpc'`.

Urutan pemeriksaan, dari yang paling murah:

1. `if not request` → tidak berlaku (cron, shell). TIDAK ada DB.
2. Allowlist jalur berbasis prefix, tanpa query: aset, static, login, logout,
   session, logo, halaman blokir, rute refresh.
3. Kill switch ICP (`presenly_saas_block_disabled`) → lolos. Dibaca lewat cache
   yang sudah ada (`odoo/addons/base/models/ir_config_parameter.py:72`).
4. Config perusahaan: `search(limit=1)`, **tanpa** `_get_or_create()`. Tidak ada
   config berarti tidak ada langganan yang bisa hangus → lolos.
5. Keputusan dari cache (0 query saat kena, lihat §5) → lolos.
6. Saringan aktor: superuser (`uid = 1`) lolos; bukan `base.group_user` (publik,
   portal) lolos; `dry_run` mencatat lalu lolos; manager di rute remediasi lolos.
7. Penolakan: rute `http` (navigasi) dijawab halaman blokir dengan **403**;
   rute `jsonrpc` (klien API, tab basi) dijawab galat JSON-RPC yang membawa
   status dan alasan, bukan HTML.

Pembagian jawaban per jenis rute memakai `rule.endpoint.routing['type']` dan
kelas dispatcher (`odoo/http.py:2395`, `:2472`, `:2543`, `:2638`).

---

## 4. Keputusan 2: siapa yang kena, perusahaan mana

| Aktor | Perlakuan | Alasan |
|---|---|---|
| Pengguna internal (`base.group_user`) | diblokir | mereka pemakai layanan berlangganan |
| Portal dan publik | tidak diblokir | mereka pelanggan tenant, bukan staf tenant. Memblokir situs publik berarti outage yang diciptakan sendiri |
| `uid = 1` (superuser) | selalu lolos | jalan pemulihan terakhir, tanpa perlu buka ICP |
| Manager `group_presenly_saas_manager` | lolos di rute remediasi saja | harus bisa memperbaiki, tanpa bisa memakai seluruh backend |
| Cron / server action / shell | tidak tersentuh lapis 1 | sinkronisasi tetap jalan, lihat §9 |

Perusahaan: **perusahaan aktif permintaan** (rekomendasi), bukan "salah satu
company pengguna sedang hangus". Pengguna yang sedang bekerja di perusahaan yang
sehat tidak boleh dihentikan. Alternatif keras (blokir bila salah satu company
hangus) dicatat sebagai opsi, bukan bawaan.

---

## 5. Biaya dan cache

**As-built.** Rencananya `ormcache` dengan nama cache sendiri. Itu batal setelah
diperiksa: di Odoo 19 nama cache terbatas pada `_REGISTRY_CACHES`
(`default`, `assets`, `stable`, `templates`, `routing`, `groups`), dan membuang
salah satunya ikut membuang cache view milik inti. Membuang cache inti setiap
kali langganan disegarkan lebih mahal daripada biaya yang hendak dihemat.

Yang dipakai sekarang: **pembacaan langsung, tanpa cache**, dengan angka
yang dikunci di tes.

| Permintaan | Query | Keterangan |
|---|---|---|
| Jalur di allowlist (aset, masuk, halaman blokir) | **0** | diperiksa sebelum basis data disentuh, diuji dengan `assertQueryCount(0)` |
| Jalur biasa, pengguna hangat | **4** | konfigurasi dan snapshot; ORM menagih dua query per model (pencarian + pembacaan kolom) |
| Permintaan pertama seorang pengguna | lebih | grup dan aturan akses, biaya satu kali per pengguna, bukan biaya gerbangnya |

Tes `test_biaya_gerbang_pada_jalur_biasa` mengunci angka 4, jadi penambahan query
tanpa sadar langsung terlihat. Kalau angka ini suatu saat terasa mahal, jalannya
adalah cache dengan pensinyalan sendiri, bukan `clear_cache` milik inti.

---

## 6. Halaman blokir

**Design Read:** halaman keadaan-terblokir di dalam produk admin yang sudah ada
(Odoo 19 backend), untuk staf tenant, memakai bahasa visual Odoo sendiri, dial
**ENERGY 1 / RHYTHM 1 / MOTION 1**.

Isi, satu titik fokus per baris, tanpa ilustrasi (R-22), tanpa angka karangan:

| Bagian | Isi | Sumber data |
|---|---|---|
| Kalimat utama | "Presenly subscription is not active for <perusahaan>" | nama company |
| Sebab | status yang benar-benar dikirim server + tanggal jawaban itu | `status`, `server_time` / `last_sync_at` |
| Akibat | "Odoo dari perusahaan ini dihentikan sampai langganan aktif kembali. Data yang sudah tersimpan tetap disimpan." | tetap, bukan karangan |
| Cara memperbaiki | Manajer: tombol **Refresh now** dan tautan **Open subscription**. Bukan manajer: "Ask your Presenly administrator to renew it." | peran |
| Kontak | hanya bila snapshot memang membawanya: `tenant_email`, `tenant_whatsapp`. Tidak ada datanya, barisnya tidak ditampilkan | snapshot, tanpa mengarang (R-23, R-38) |

Aturan yang dipatuhi, dan cara membuktikannya di F2:

- **R-26**: hanya dua kontrol, keduanya bekerja (refresh memanggil
  `action_refresh_subscription` lewat rute `POST` dengan CSRF, tautan membuka
  halaman Langganan). Tidak ada tombol hiasan.
- **R-27**: tombol refresh punya keadaan: mengirim, berhasil (status berubah),
  gagal (pesan galat dari server ditampilkan apa adanya).
- **R-25/R-32**: warna dari token Odoo (`alert-danger`), kontras ikut tema,
  bisa dijangkau Tab, fokus terlihat, tombol bisa diaktifkan Enter/Space.
- **R-02**: tanpa em dash di seluruh string, termasuk `.po`.
- **R-15/R-16**: label tindakan spesifik ("Refresh subscription", bukan "Get
  Started" / "Learn more"), tanpa kata pemasaran.
- **R-34**: aman di mode gelap karena memakai token tema, bukan palet sendiri.
- Tidak membocorkan rahasia: halaman dirender dari field aman saja, **tanpa**
  `api_key`, `webhook_secret`, atau `webhook_token`.

Status HTTP: **403** untuk navigasi (autentikasi berhasil, otorisasi tidak),
dengan halaman kita, bukan halaman bawaan Werkzeug. Untuk klien JSON-RPC,
galat JSON-RPC yang membawa kode dan alasan yang sama.

Halaman ini memakai `web.layout` supaya bentuknya konsisten dengan backend dan
tidak mendefinisikan palet baru. Konsekuensinya `/web/assets/*` harus ada di
allowlist, dan itu sudah ada.

Delivery Gate untuk halaman ini dijalankan di akhir F2 (§11).

---

## 7. Keputusan 3: fail-open atau fail-closed

Dua hal berbeda yang hari ini tercampur:

| Keadaan | Sifat | Bawaan yang diusulkan |
|---|---|---|
| Server **menjawab** status negatif (`expired`, `suspended`, trial lewat tanggal) | fakta | **memblokir** |
| Server **tidak bisa dihubungi** melewati `offline_grace_days` | dugaan | **memblokir, tetapi hanya bila dinyalakan** |

- Bawaan `offline_grace_days = 0` berarti fail-open seperti hari ini: jaringan
  putus tidak pernah mengunci siapa pun.
- Bila dinyalakan, nilainya harus besar (rekomendasi 14 hari) supaya gangguan
  jaringan biasa tidak mengunci seluruh pegawai, dan remediasi manajer (§8)
  wajib sudah ada lebih dulu.
- `Masa Tenggang` yang sudah ada diberi **satu arti saja**: tenggang konfirmasi
  offline. Help-nya ditulis ulang, `_effective_state()` akhirnya memakainya, dan
  banner memakai ambang yang sama supaya tidak ada dua arti untuk satu kata.
  Ini sekaligus menutup temuan di §0.

---

## 8. Escape hatch (wajib ada sebelum F2 dinyalakan)

| Jalur | Cara memakainya | Siapa |
|---|---|---|
| Kill switch `presenly_saas_block_disabled` | `odoo-bin shell`, atau mengubah satu baris ICP | operator saat insiden |
| Superuser `uid = 1` | selalu lolos | pemulihan darurat |
| Override sementara | kolom di config: berlaku sampai kapan + alasan + baris audit | support, dengan jejak |
| Halaman blokir | refresh dan buka halaman Langganan | manajer |
| CLI | `odoo-bin -u presenly_saas` dan `shell` | pemulihan dan pemutakhiran modul saat diblokir |
| Log transisi | satu `warning` saat blokir mulai dan saat berakhir, per company | siaga |

Tanpa jalur-jalur ini, kesalahan konfigurasi pertama berubah menjadi insiden
produksi. Karena itu urutannya: escape hatch dibangun di F1, gerbang dinyalakan
di F4.

---

## 9. Yang tetap jalan saat diblokir, dan mengapa

| Hal | Perlakuan | Alasan |
|---|---|---|
| Cron sinkronisasi dan penarikan | tetap jalan (bukan HTTP, jadi tidak tersentuh) | tenant yang memperpanjang harus langsung terpakai, bukan menunggu tarikan penuh |
| Cermin data lama | tetap disimpan, tidak dihapus | retensi sudah punya aturannya sendiri |
| Webhook `/presenly_saas/webhook/<token>` | **keputusan, §14** | rekomendasi: dibiarkan, supaya cermin tetap segar dan webhook bukan pintu masuk manusia |
| API mobile `/api/presenly/v1/*` | **keputusan, §14** | rekomendasi: diblokir, karena itu pintu masuk pegawai |
| Laporan PDF/XLSX | diblokir | laporan adalah cara membaca data keluar |
| Pemutakhiran modul dari UI | ikut diblokir (jalur CLI tetap ada) | konsisten dengan "backend dihentikan", dan dicatat di dokumen pemulihan |

---

## 10. Mode dry run (yang membuat peluncuran ini aman)

`block_mode`: `off` / `dry_run` / `enforce`.

- `dry_run` menghitung keputusan, mencatatnya, dan menambah penghitung di
  halaman Langganan ("N permintaan akan diblokir dalam 7 hari terakhir"),
  tanpa memblokir apa pun.
- **Kriteria Go:** 7 hari `dry_run` pada tenant sehat dengan nol permintaan
  yang akan diblokir. Baru setelah itu `enforce`.
- `off` adalah bawaan saat upgrade, jadi tidak ada tenant yang terkunci oleh
  pemutakhiran modul (§12).

---

## 11. Fase

| Fase | Isi | Berkas | Kriteria terima |
|---|---|---|---|
| **F1** | Fungsi keputusan + cache + `block_mode` + kill switch + log transisi + penghitung dry run | `models/presenly_saas_guard.py`, `models/presenly_saas_subscription.py`, `models/presenly_saas_config.py`, `models/res_config_settings.py`, `views/res_config_settings_views.xml`, `views/presenly_saas_subscription_views.xml` | matriks uji §12 hijau; anggaran query sama; `enforce` belum mengubah perilaku apa pun selain log |
| **F2** | Gerbang `ir.http` + allowlist + halaman blokir + remediasi manajer | `models/ir_http.py`, `controllers/blocked.py`, `views/presenly_saas_blocked_templates.xml`, `security/`, `i18n/id.po` | daftar click-through §12 direkam; Delivery Gate halaman blokir bersih |
| **F3** | Bila scope data dipilih: filter menu dan action milik modul Presenly + shell remediasi | `models/ir_ui_menu.py` | menu tenant hangus vs sehat; uji "guard the guard" hijau |
| **F4** | Fail-closed (`offline_grace_days`) + override sementara + audit | `models/presenly_saas_config.py`, `models/presenly_saas_guard.py`, view | matriks grace hijau; override terpakai dan tercatat |
| **F5** | Opsional: kunci tulis ORM untuk opsi C | `models/presenly_saas_guard_orm.py` | tulis ditolak, baca lolos, cron lolos dengan skip context |
| **F6** | Operasional: README §baru, `PLAN.md` §1.2b kedua, prosedur pemulihan, checklist go-live | dokumentasi | tidak ada perilaku yang belum tertulis |

F1 dan F2 wajib. F3 dan seterusnya mengikuti keputusan §14.

---

## 12. Rencana uji

**TransactionCase** (perluasan `tests/test_guard_contract.py`): matriks
`block_mode × scope × status × state_source × grace × company × peran`, termasuk
kasus yang hari ini sudah dijaga (cached/unreachable tidak pernah memblokir,
tanpa snapshot tidak memblokir) dan kasus baru (dua company, satu hangus).

**HttpCase baru `tests/test_guard_http.py`**, dengan daftar kasus yang jadi bukti
R-35 saat F2:

| Permintaan | Aktor | Harapan |
|---|---|---|
| `GET /odoo` | internal, tenant hangus | 403 halaman blokir, memuat status dan tanggal jawaban server |
| `POST /web/dataset/call_kw` | internal, tenant hangus | galat JSON-RPC dengan alasan, bukan HTML |
| `GET /web/assets/...`, `GET /web/login`, `GET /logo` | siapa pun | 200 |
| `GET /presenly_saas/blocked` | internal, tenant hangus | 200 |
| `POST /presenly_saas/blocked/refresh` | manajer | snapshot jadi `live`, permintaan berikutnya 200 |
| `POST /presenly_saas/blocked/refresh` | bukan manajer | ditolak 403 |
| `GET /odoo` | pengguna perusahaan sehat | 200 seperti biasa |
| `GET /odoo` | portal dan publik | 200 |
| `GET /report/pdf/...` | internal, tenant hangus | 403 |
| `GET /api/presenly/v1/attendance/status` | internal, tenant hangus | galat JSON-RPC (bila §14 memutuskan diblokir) |
| `GET /odoo` | internal, tenant hangus, `dry_run` | 200, ada baris log, penghitung bertambah |
| `GET /odoo` | internal, tenant hangus, kill switch hidup | 200 |

Tambahan:

- **Anggaran query**: `assertQueryCount` pada permintaan sehat, sebelum dan
  sesudah.
- **Guard the guard**: setiap modul bernama `presenly*` harus terdaftar di
  konstanta modul Presenly atau disebut eksplisit sebagai pengecualian, supaya
  modul pendamping baru tidak lolos diam-diam.
- **Suite lama tetap hijau** dengan `block_mode = off` bawaan: `presenly`,
  `presenly_saas`, `presenly_saas_hr`, termasuk HttpCase yang sudah ada
  (`presenly/tests/test_api_*.py`, `presenly_saas_hr/tests/test_webhook_receiver.py`).

---

## 13. Risiko

| Risiko | Mitigasi |
|---|---|
| Mengunci diri sendiri dari backend | kill switch ICP, superuser selalu lolos, CLI, `dry_run` sebelum `enforce`, kriteria Go §10 |
| Modul tidak bisa dimutakhirkan dari UI saat tenant hangus | jalur CLI didokumentasikan; pengecualian khusus untuk rute pemutakhiran bisa diputuskan di F2 |
| Tes HttpCase lama ikut terkunci | bawaan `off` saat upgrade, migrasi menulis nilai eksplisit |
| Kinerja turun per permintaan | cache dengan masa berlaku di dalam nilai; uji anggaran query |
| Multi-company membingungkan | keputusan §14 nomor 3; banner sudah per company |
| API mobile/webhook mati tanpa diinginkan | keputusan §14 nomor 4 |
| `enforce` dipakai pada tenant yang membeli aplikasi Odoo lain | keputusan §2; bila opsi C dipilih, gerbangnya sama, hanya pemetaan izinnya berbeda |
| Galat pada lapis `ir.http` mematikan seluruh backend | seluruh badannya dibungkus try/except dengan sikap lolos, dan kegagalannya dicatat; blokir hanya keluar dari jalur yang berhasil dihitung |

---

## 14. Pertanyaan yang harus dijawab sebelum F2

1. **Scope**: A (backend penuh) atau C (kunci tulis)? Rekomendasi **A**.
2. **Fail policy**: tetap fail-open, atau memblokir setelah N hari tanpa
   konfirmasi? Rekomendasi **memblokir setelah 14 hari**, dinyalakan di F4.
3. **Multi-company**: blokir berdasar perusahaan aktif (rekomendasi) atau bila
   salah satu perusahaan pengguna hangus?
4. **API mobile `/api/presenly/v1/*` dan webhook `/presenly_saas/webhook/`**:
   ikut diblokir? Rekomendasi **API diblokir, webhook dibiarkan**.

---

## 16. Catatan as-built

Yang berbeda dari rencana di atas, dan alasannya:

| Rencana | As-built | Alasan |
|---|---|---|
| Cache `ormcache` untuk fakta penegakan (§5) | Pembacaan langsung, 0 query di jalur allowlist dan 4 query di jalur biasa | Nama cache di Odoo 19 terbatas; membuang satu nama ikut membuang cache view inti |
| `block_mode` sebagai satu-satunya sakelar | `block_mode` terpisah dari `guard_mode` | Dua pertanyaan berbeda: `guard_mode` mengatur API yang dipanggil modul lain, `block_mode` mengatur gerbang. Menggabungkannya membuat satu setelan berarti dua hal |
| Halaman blokir menautkan "Open subscription" | Tidak ada tautan itu; ada **Refresh subscription** dan formulir **Change the connection** | Dengan scope A, halaman Langganan ada di dalam backend yang justru ditutup. Tautan ke halaman yang tidak bisa dibuka lebih buruk daripada tidak ada tautan |
| Shell remediasi di F3 | Formulir perbaikan koneksi di halaman blokir | Kebutuhannya lebih sempit dari perkiraan: yang perlu diperbaiki saat ditutup hanya alamat, tenant code, dan kunci API |
| `block_since` disimpan di snapshot | Disimpan di konfigurasi | Snapshot ditulis ulang setiap penyegaran; penandanya harus bertahan melewatinya |
| `offline_grace_days` sebagai field baru | Memakai `grace_days` yang sudah ada, dengan satu arti | Dua field dengan arti berdekatan selalu berakhir berbeda tafsir. Efek sampingnya: banner berubah dari peringatan ke bahaya pada ambang yang sama, dan itu memang satu momen |

Temuan yang tidak ada di rencana dan hanya ketahuan dari tes HTTP:

- **`/odoo` memakai `auth='none'`.** Gerbang yang hanya melihat `env.uid`
  meloloskan kerangka backend, yaitu justru permukaan yang paling perlu ditutup:
  di dalamnya ada menu dan seluruh bundel aplikasi. Gerbang sekarang membaca
  `request.session.uid` bila `env.uid` kosong, dan perusahaan yang diperiksa
  diambil dari pengguna sesi itu. Tesnya:
  `test_backend_dialihkan_ke_halaman_blokir`.
- **`allow_redirects=False` di teslah yang menemukannya.** Tes yang hanya
  memeriksa halaman akhir akan melihat halaman blokir dan menyimpulkan semuanya
  beres, padahal shell-nya sudah tersaji lebih dulu.
- **Rute modul sendiri bekerja di lingkungan tes.** Catatan lama di
  `presenly_saas_hr/tests/test_webhook_receiver.py` menyebut rute modul selalu
  404 di `HttpCase`; untuk rute `/presenly_saas/blocked` tidak demikian, jadi
  halaman blokir, peran manajer, dan kebocoran kunci API ikut diuji lewat HTTP.

Angka uji saat penyerahan: **334 kasus** untuk `presenly_saas` (0 gagal, 1 error
lintas modul yang sudah ada sebelumnya: `presenly.saas.employee` milik
`presenly_saas_hr`) dan seluruh suite `presenly_saas_hr` hijau di basis data yang
memasang keduanya.

---

## 17. Yang sengaja tidak dilakukan

- Tidak menyentuh satu berkas pun di `custom_addons/presenly`.
- Tidak menonaktifkan pengguna dan tidak mencabut grup atau ACL. Itu kunci yang
  sulit dibuka kembali dan meninggalkan jejak salah di audit.
- Tidak memblokir login, aset, situs publik, atau portal.
- Tidak menaruh gerbang di lapisan ORM sejak awal.
- Tidak menulis apa pun ke basis data per permintaan. Log hanya untuk transisi
  blokir dan untuk agregat `dry_run`.
- Tidak memakai `ir.config_parameter` untuk setelan. Satu kunci, hanya untuk
  kill switch darurat.
