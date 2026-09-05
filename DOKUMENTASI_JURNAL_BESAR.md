# Dokumentasi Perubahan dan Flow Jurnal Besar

Modul: `custom_addons/sif_keuangan`  
Branch kerja: `feat/keuangan-jurnal-besar`

## Tujuan Modul

Modul Jurnal Besar dipakai untuk mencatat transaksi keuangan, memvalidasi debit dan kredit, lalu menampilkan laporan Buku Besar per akun dan periode bulanan.

Flow utama:

```text
Master COA
-> Input Jurnal Dasar / Otomatis dari PPL
-> Validasi Debit = Kredit
-> Posting
-> Buku Besar
-> Filter Bulan / Akun / Unit
```

---

## 1. Master COA

Menu:

```text
Keuangan -> Konfigurasi -> Master COA
```

### Sebelum Diubah

- COA hanya daftar akun biasa.
- Struktur akun masih datar.
- Belum ada relasi induk akun.
- Belum ada level akun otomatis.

Contoh lama:

```text
Kas
Bank
Beban Gaji
Pendapatan
```

### Sesudah Diubah

Ditambahkan field:

- `parent_id`: induk akun.
- `level`: level akun otomatis berdasarkan induk akun.

Contoh struktur baru:

```text
1.0.0 Aset
  1.1.0 Kas dan Bank
    1.1.1 Kas Operasional
    1.1.2 Bank Operasional

5.0.0 Beban
  5.1.0 Beban Operasional
    5.1.1 Beban ATK
    5.1.2 Beban Gaji
```

### Efek ke Flow

- User harus punya COA sebelum input jurnal.
- Akun jurnal mengikuti struktur ERD.
- Buku Besar lebih mudah dibaca per kelompok akun.

---

## 2. Input Jurnal Dasar

Menu:

```text
Keuangan -> Jurnal Besar -> Input Jurnal Dasar
```

### Sebelum Diubah

- Sudah bisa input header jurnal dan baris debit-kredit.
- Belum ada helper periode bulanan.
- Belum ada data periode siap pakai untuk Buku Besar.

### Sesudah Diubah

Ditambahkan helper periode otomatis dari tanggal jurnal:

- `period_month`
- `period_year`
- `period_key`

Contoh:

```text
Tanggal: 05/09/2026
Period Month: 9
Period Year: 2026
Period Key: 2026-09
```

### Cara Input

1. Buka menu `Input Jurnal Dasar`.
2. Klik `New`.
3. Isi header:
   - Tanggal jurnal.
   - Memo/keterangan.
   - Unit/departemen.
   - Dokumen sumber jika ada.
4. Tambahkan baris jurnal minimal dua baris.
5. Isi akun, debit, kredit, dan keterangan.
6. Pastikan total debit sama dengan total kredit.
7. Klik validasi/posting.

Contoh transaksi:

```text
Pembelian ATK Rp250.000 pakai kas
```

Baris debit:

```text
Akun: 5.1.1 Beban ATK
Debit: 250.000
Kredit: 0
```

Baris kredit:

```text
Akun: 1.1.1 Kas Operasional
Debit: 0
Kredit: 250.000
```

---

## 3. Validasi dan Posting

### Fungsi

Validasi memastikan jurnal sudah benar sebelum masuk Buku Besar.

### Aturan

- Baris jurnal tidak boleh kosong.
- Total debit harus sama dengan total kredit.
- Jika tidak balance, posting ditolak.
- Jika balance, status berubah dari `Draft` ke `Posted`.
- Nomor jurnal otomatis dibuat.

Contoh nomor jurnal:

```text
JRN/202609/0001
```

### Efek ke Flow

- Jurnal posted menjadi transaksi resmi.
- Hanya jurnal posted yang masuk Buku Besar.

---

## 4. Buku Besar

Menu:

```text
Keuangan -> Jurnal Besar -> Buku Besar
```

### Sebelum Diubah

- Buku Besar masih berupa list baris jurnal biasa.
- Belum ada saldo mutasi.
- Belum ada filter bulanan Januari sampai Desember.
- Belum ada grouping periode bulanan.

### Sesudah Diubah

Ditambahkan:

- `balance`: saldo mutasi.
- `period_key`: periode format `YYYY-MM`.
- Filter bulan Januari sampai Desember.
- Grouping akun, periode, unit, dan tanggal.

Kolom yang tampil:

```text
Tanggal
Nomor Jurnal
Akun
Kategori Akun
Keterangan
Unit
Debit
Kredit
Saldo Mutasi
Periode
Status
```

Contoh hasil transaksi ATK:

```text
Akun Beban ATK
Debit: 250.000
Kredit: 0
Saldo Mutasi: 250.000

Akun Kas Operasional
Debit: 0
Kredit: 250.000
Saldo Mutasi: -250.000
```

### Catatan

Buku Besar bukan tempat input manual. Data berasal otomatis dari jurnal yang sudah `Posted`.

---

## 5. Filter Bulanan

Lokasi:

```text
Buku Besar -> Search / Filter
```

### Fungsi

Filter bulanan dipakai untuk laporan Buku Besar per periode sesuai SRS.

Filter tersedia:

```text
Januari
Februari
Maret
April
Mei
Juni
Juli
Agustus
September
Oktober
November
Desember
```

Grouping tersedia:

```text
Akun
Periode Bulanan
Unit
Tanggal
```

Contoh:

```text
Pilih filter September
-> Sistem tampilkan transaksi dengan period_key 2026-09
```

---

## 6. Hak Akses / Security

### Sebelum Diubah

- User internal Odoo bisa create, edit, dan delete data keuangan.
- Akses terlalu bebas.
- Belum sesuai RBAC SRS.

### Sesudah Diubah

Hak akses dipisah:

- `Internal User`: read-only.
- `Keuangan SIFNEXT: Staf`: full CRUD untuk modul keuangan.
- `Keuangan SIFNEXT: Super User`: mewarisi akses staf.

Efek:

- Jika user belum masuk grup keuangan, tombol `New` tidak muncul.
- Tombol `New` muncul di `Master COA` dan `Input Jurnal Dasar` jika user punya grup keuangan.
- `Buku Besar` tetap laporan, jadi tidak perlu input manual.

---

## 7. Integrasi PPL

### Fungsi

Modul PPL bisa membuat jurnal otomatis setelah dokumen PPL disetujui.

Flow:

```text
User buat PPL
-> PPL disetujui
-> Sistem membuat jurnal otomatis
-> Nomor PPL masuk ke Dokumen Sumber
-> Debit dan kredit dibuat otomatis
-> Jika balance, jurnal posted
-> Masuk Buku Besar
```

Contoh PPL pembayaran gaji:

```text
Debit:
5.1.2 Beban Gaji = 15.000.000

Kredit:
1.1.2 Bank Operasional = 15.000.000

Dokumen Sumber:
PPL/202609/0001
```

Hasil:

```text
Jurnal: JRN/202609/0002
Status: Posted
Tampil di Buku Besar
```

---

## 8. Docker dan Database

### Sebelum Diubah

- Docker sempat berjalan dari folder lama:

```text
C:\odoo
```

- Bukan dari repo GitHub tim:

```text
C:\werk\odoo
```

- Database lama `db_d` punya sisa modul dan error aset.

### Sesudah Diubah

Database fresh:

```text
db_sifnext
```

Odoo web valid:

```text
http://localhost:8069/web/login
HTTP 200 OK
```

---

## Flow Akhir Setelah Perubahan

```text
1. Admin beri user akses Keuangan SIFNEXT: Staf / Super User
2. User buka Master COA
3. User buat struktur akun sesuai ERD
4. User buka Input Jurnal Dasar
5. User isi header jurnal
6. User isi baris debit dan kredit
7. Sistem cek total debit = total kredit
8. User klik validasi/posting
9. Status berubah Draft ke Posted
10. Baris jurnal otomatis masuk Buku Besar
11. User filter Buku Besar per bulan, akun, unit, atau tanggal
```

---

## Ringkasan Perubahan Paling Penting

```text
COA flat
menjadi
COA hirarki sesuai ERD
```

```text
Buku Besar list biasa
menjadi
Buku Besar dengan saldo mutasi dan filter bulanan sesuai SRS
```

```text
Akses bebas
menjadi
akses input hanya untuk grup Keuangan SIFNEXT
```
