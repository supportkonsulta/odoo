# Perkakas pemeliharaan

Skrip di sini bekerja **di luar Odoo**, langsung ke PostgreSQL. Itu disengaja:
keduanya memperbaiki keadaan yang membuat Odoo gagal memuat registry, sehingga
tidak bisa dijalankan sebagai modul.

Jalankan dengan Python milik Odoo supaya `psycopg2` tersedia:

```bash
./odoo-venv/bin/python3 tools/<skrip>.py --db <nama-db> ...
```

---

## `cleanup_orphan_tables.py`

Membuang tabel dan view sisa milik modul yang sudah tidak terpasang, dan
memperbaiki yang masih bisa diperbaiki.

### Masalah yang diselesaikannya

Pada database yang pernah memuat modul lain, tabelnya bisa tertinggal **tanpa
primary key**. Saat Odoo memasang modul yang membutuhkan tabel itu, Odoo
menemukannya "sudah ada" sehingga tidak membuat ulang, lalu gagal menambahkan
foreign key:

```
ALTER TABLE res_company ADD FOREIGN KEY (resource_calendar_id)
  REFERENCES resource_calendar(id)
ERROR: there is no unique constraint matching given keys
```

Modul yang gagal tidak ada hubungannya dengan tabel yang rusak, sehingga
penyebabnya sulit dilihat.

### Dasar pemilihan

Bukan tebakan, keduanya diperiksa:

1. **Odoo selalu membuat primary key**, termasuk pada tabel relasi many-to-many
   yang memakai primary key gabungan. Database sehat: 0 tabel tanpa primary key.
2. **Saat modul di-uninstall, Odoo menghapus catatan modelnya** dari `ir_model`.
   Jadi model yang masih terdaftar berarti milik modul yang masih terpasang.

Karena itu: *tanpa primary key* **dan** *tanpa model terdaftar* berarti tabel
sisa, dan tidak dipakai modul terpasang mana pun.

### Yang tidak pernah dibuang

- tabel yang modelnya masih terdaftar
- tabel berisi data, kecuali diminta lewat `--drop-with-data`
- view yang namanya sama dengan tabel model terdaftar (model `_auto = False`)
- apa pun di luar skema `public`

### Pemakaian

```bash
# 1. Lihat daftarnya, dengan jumlah baris dan penanda id ganda
./odoo-venv/bin/python3 tools/cleanup_orphan_tables.py --db odoo --list

# 2. Lihat rencananya (tidak mengubah apa pun)
./odoo-venv/bin/python3 tools/cleanup_orphan_tables.py --db odoo --dry-run

# 3. Cadangkan dulu
pg_dump -h 127.0.0.1 -U root -d odoo -Fc -f /tmp/odoo-sebelum.dump

# 4. Buang yang kosong, dan PERBAIKI yang masih sehat
./odoo-venv/bin/python3 tools/cleanup_orphan_tables.py --db odoo \
    --apply --repair --backup-file /tmp/odoo-sebelum.dump
```

`--apply` menolak jalan tanpa `--backup-file` yang ada dan tidak kosong. Seluruh
perubahan berada dalam satu transaksi: bila ada satu saja yang gagal, semuanya
dibatalkan dan tidak ada yang terhapus.

### `--repair` lebih dulu daripada `--drop-with-data`

`--repair` menambahkan primary key pada tabel sisa yang **id-nya unik dan tidak
kosong**, sehingga datanya selamat dan Odoo bisa memakainya lagi. Yang tidak bisa
diperbaiki dilaporkan beserta alasannya:

| Alasan | Arti |
|---|---|
| `N id ganda` | tabelnya memang sudah rusak; membersihkan duplikat adalah keputusan pemilik data |
| `tanpa kolom id` | tabel relasi; primary key-nya gabungan kolom lain yang tidak bisa ditebak skrip |

### Batas yang perlu diketahui

Memperbaiki skema **tidak** memperbaiki data. Bila baris pada tabel sisa menunjuk
baris yang sudah tidak ada, Odoo tetap gagal saat menambahkan foreign key:

```
ALTER TABLE discuss_channel_member ADD FOREIGN KEY (partner_id) ...
ERROR: violates foreign key constraint
```

Itu masalah data, dan hanya pemilik data yang bisa memutuskan apakah barisnya
dibuang. Untuk kasus seperti itu, database baru atau pemulihan dari cadangan yang
sehat lebih masuk akal daripada menambal lebih jauh.
