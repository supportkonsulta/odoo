# Kebutuhan Bisnis dan Spesifikasi Alur Kerja Modul Engineering

## 1. Pendahuluan

Modul Engineering ini dibangun untuk mendigitalisasi dan mengotomatisasi proses pelaksanaan proyek yang sebelumnya manual (menggunakan Excel dan dokumen terpisah). Modul ini bertindak sebagai jembatan yang menerima data dari fungsi Penjualan (Sales) yang telah memenangkan proyek, mengelolanya melalui fase eksekusi lapangan, hingga menghasilkan dokumen serah terima (BAP/BAST) yang valid untuk ditagihkan oleh fungsi Penagihan (Billing).

**Tujuan Utama:**

1. Menghilangkan entri data ganda dari fase penjualan ke eksekusi.

2. Mengotomatisasi jadwal (Master Schedule), struktur pekerjaan (WBS), dan perhitungan bobot progres.

3. Mendigitalisasi laporan harian, mingguan, dan bulanan secara berjenjang.

4. Memberikan peringatan dini otomatis jika realisasi proyek tertinggal dari rencana (Kurva-S).

5. Menghasilkan dokumen BAP/BAST ber-Tanda Tangan Digital yang langsung bisa digunakan untuk penagihan.

## 2. Hak Akses dan Peran Pengguna (Role-Based Access)

Sistem harus membedakan hak akses berdasarkan peran dan penugasan proyek. Pengguna hanya boleh melihat dan memproses data pada **proyek yang secara spesifik ditugaskan kepadanya**.

1. **Pelaksana (Lapangan):** Membuat laporan harian dan mengunggah bukti pekerjaan (foto/dokumen). Mengakses sistem utamanya bisa via perangkat seluler (Mobile).

2. **Engineer / Design Engineer:** Mengelola struktur pekerjaan (WBS) dan dokumen teknis kelengkapan proyek.

3. **Pengawas (Lapangan/Mekanikal/Elektrikal):** Mengonsolidasi laporan harian dari Pelaksana, merangkumnya, dan meneruskannya ke atasan.

4. **Supervisor / Kepala Regu:** Meninjau, merevisi, atau menyetujui laporan konsolidasi dari Pengawas. Menangani peringatan dini jika ada keterlambatan.

5. **Kepala Unit / Project Manager (PM) / Team Leader:** Jenjang persetujuan (approval) tertinggi. Berwenang memberikan otorisasi khusus (misal: pekerjaan di luar jadwal) dan menyetujui BAP/BAST secara digital.

6. **Penagihan (Billing):** Hanya memiliki hak **baca (read-only)** terhadap status persetujuan BAP/BAST dan dokumen pendukungnya. Tidak boleh merubah data apapun di modul Engineering.

## 3. Alur Bisnis Utama (Core Business Flows)

### A. Alur Inisiasi Proyek & Dokumen Prasyarat

1. Ketika suatu proyek/kontrak disetujui di fungsi Penjualan, seluruh informasi dasarnya (klien, nilai kontrak, tanggal mulai-selesai, dan daftar periksa/checklist dokumen teknis) otomatis terhubung dan dapat diakses oleh tim Engineering. Sistem akan memberikan notifikasi bahwa ada proyek baru aktif.

2. Sebelum pekerjaan lapangan bisa dicatat, tim Engineering harus memastikan kelengkapan izin kerja.

3. **Validasi Keselamatan (Safety First):** Dokumen "Working Permit" dan "Safety Induction" **wajib** berstatus lengkap/terlampir. Jika tidak, sistem harus memblokir pengisian aktivitas/laporan lapangan apapun.

4. Tim engineering menentukan personel dalam proyek tersebut dengan jabatan masing masing (buat tampilannya mudah dipahami dan user friendly jelas misalnya seperti struktur personel ini untuk project ini.)

### B. Alur Perencanaan (WBS & Master Schedule)

1. Tim Engineer membuat urutan pekerjaan secara hierarkis (Pekerjaan Utama dan Sub-pekerjaan), untuk tampilannya buat se friendly mungkin untuk user dan mudah dilihat keseluruhan wbsnya misalnya terlihat dengan jelas bahwa ini subnya ini mungkin dibuat bentuk baris? dimana bisa ditambahkan baris bawahnya untuk pekerjaan selanjutnya atau juga sub atau sub subnya kemudian di sebelah kanan muncul halaman detailnya jika baris itu diklik yg merupakan juga sebagai inputan detail detail pekerjaannya itu tadi.

2. Untuk setiap pekerjaan, pengguna menginput: Nama Pekerjaan, Nilai Pekerjaan, Volume, Tanggal Mulai, dan Tanggal Selesai.

3. **Logika Otomatisasi:**

   * **Validasi Tanggal:** Sistem mengecek apakah Tanggal Mulai dan Selesai pekerjaan berada di dalam rentang waktu kontrak proyek. Jika di luar rentang, sistem menolak input tersebut kecuali PM memberikan "Otorisasi Luar Periode", dan otomatis juga mendeteksi hari libur atau sabtu/ minggu sehingga waktu kerja sesuai kalender hari kerja secara otomatis.

   * **Kalkulasi Bobot:** Sistem otomatis menghitung persentase bobot setiap pekerjaan dengan rumus: `(Nilai Pekerjaan / Total Nilai Kontrak) * 100`. Jika kontrak mengalami adendum (perubahan nilai) di masa depan, bobot ini harus dikalkulasi ulang secara otomatis.

   * **Jadwal & Progres Rencana:** Sistem otomatis memecah durasi kontrak menjadi periode mingguan. Bobot pekerjaan akan didistribusikan secara proporsional ke dalam minggu-minggu tersebut untuk membentuk "Progres Rencana Mingguan" dan "Kumulatif".

     UNTUK MASTER SCHEDULE NANTI OUTPUTNYA ADALAH BERBENTUK SEPERTI GANNT CHART

### C. Alur Pelaksanaan & Pelaporan Berjenjang

1. **Laporan Harian (Daily Report) - *Harus Mobile-Friendly*:**

   * Pelaksana membuka aplikasi di lapangan (sistem harus responsif di HP) lalu memilih proyek dan tanggal.

   * Pelaksana mengisi: Jam mulai-selesai, pekerja yang hadir, memilih pekerjaan (WBS) yang dikerjakan, input persentase progres hari itu, deskripsi pekerjaan, dan **wajib** mengunggah bukti/dokumentasi foto (Evidence).

   * Setelah disubmit, laporan masuk ke Pengawas.

   * *Pengingat Otomatis:* Jika Pelaksana telat membuat laporan hingga H+1, sistem akan mengirimkan notifikasi peringatan.

2. **Konsolidasi (Pengawas):**

   * Pengawas mengumpulkan beberapa Laporan Harian yang masuk, merangkumnya menjadi Laporan Konsolidasi, lalu mengajukannya ke Supervisor.

3. **Persetujuan (Supervisor):**

   * Supervisor mereview Laporan Konsolidasi.

   * Jika "Revisi": Supervisor wajib mengisi alasan/catatan revisi, dan laporan kembali ke Pengawas.

   * Jika "Disetujui": Data progres otomatis terekam secara sah.

4. **Pembentukan Laporan Periodik Otomatis:**

   * Secara terjadwal (misal: di akhir minggu dan akhir bulan), sistem akan mengumpulkan semua laporan yang **sudah disetujui** dalam periode tersebut dan membentuk "Weekly Report" (Laporan Mingguan) dan "Monthly Report" (Laporan Bulanan) tanpa campur tangan/input manual sama sekali.

### D. Alur Pemantauan (Monitoring & Kurva-S)

1. Sistem terus membandingkan "Progres Rencana" (dari WBS) dengan "Progres Aktual" (dari Laporan Mingguan/Bulanan yang disetujui).

2. Perbandingan ini divisualisasikan dalam bentuk grafik Kurva-S.

3. **Deteksi Keterlambatan:** Sistem menghitung selisih (Variance) = Progres Aktual - Progres Rencana. Jika hasilnya negatif dan melewati batas toleransi tertentu (misal: -5%), sistem otomatis memicu peringatan berwarna merah dan mengirim pesan notifikasi darurat kepada Supervisor dan PM bahwa proyek terancam terlambat.

### E. Alur Penyelesaian (BAP / BAST)

1. Berdasarkan Laporan Mingguan/Bulanan yang disetujui, PM dapat membuat dokumen Berita Acara Pelaksanaan/Serah Terima (BAP/BAST).

2. BAP/BAST melalui proses persetujuan oleh Kepala Unit / PM yang disahkan dengan pembubuhan Tanda Tangan Digital di dalam sistem (menggantikan tanda tangan basah/kertas).

3. Setelah BAP/BAST disetujui, status proyek berubah menjadi "BAP/BAST Disetujui".

4. Status ini akan dibaca secara otomatis oleh fungsi Penagihan (Billing). Selama status ini belum tercapai, sistem Penagihan tidak akan bisa menerbitkan Invoice.

## 4. Rangkuman Logika Validasi Ketat (Business Rules)

Agar AI Agent tidak melewatkan logika penting, perhatikan aturan baku berikut yang tidak boleh dilanggar dalam penulisan kode:

* **RULE-01 (Akses Terisolasi):** Karyawan hanya bisa melihat data dan menu untuk proyek di mana nama mereka didaftarkan pada sesi penugasan.

* **RULE-02 (Validasi Keselamatan Mutlak):** Tidak ada tombol atau akses untuk menyimpan/mengirim aktivitas lapangan jika sistem membaca dokumen izin keselamatan di level proyek belum lengkap.

* **RULE-03 (Batas Waktu Kontrak):** Validasi tanggal pekerjaan pada kalender penjadwalan mutlak harus berada di dalam *start date* dan *end date* proyek.

* **RULE-04 (Hierarki Persetujuan Kaku):** Status laporan tidak boleh dilompat. Harus urut: Draft (Pelaksana) -> Konsolidasi (Pengawas) -> Menunggu Persetujuan (Supervisor) -> Disetujui/Ditolak.

* **RULE-05 (Catatan Penolakan):** Fungsi tolak/revisi dokumen apapun (laporan maupun BAP) wajib memunculkan kolom pengisian alasan (mandatory field).

* **RULE-06 (Integrasi Lintas Modul):** Data klien, nilai proyek, dan daftar ceklis murni dibaca dari sumber awal (Penjualan). Modul ini tidak boleh membuat duplikat database penyimpanannya sendiri untuk data-data master tersebut.

* **RULE-07 (Jejak Audit):** Setiap kali status laporan atau dokumen BAP berubah, sistem harus mencatat rekam jejaknya (Siapa yang mengubah, kapan diubah, dari status apa menjadi apa) secara otomatis di bawah dokumen terkait.

  INTINYA BUAT MODULE INI MUDAH DIGUNAKAN, FLOWNYA JELAS DAN TAMPILANNYA NANTI MUDAH DIPAHAMI DAN MUDAH DIGUNAKAN TETAPI LENGKAP SEMUA JUGA.