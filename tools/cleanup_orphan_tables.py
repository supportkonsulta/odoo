#!/usr/bin/env python3
"""Buang tabel dan view sisa milik modul yang sudah tidak terpasang.

Kenapa perlu: pada database yang pernah memuat modul lain, tabelnya bisa
tertinggal dalam keadaan tanpa primary key. Saat Odoo memasang modul yang
membutuhkan tabel itu, Odoo menemukannya "sudah ada" sehingga tidak membuat ulang,
lalu gagal menambahkan foreign key:

    ALTER TABLE res_company ADD FOREIGN KEY (resource_calendar_id)
      REFERENCES resource_calendar(id)
    ERROR: there is no unique constraint matching given keys

Modul yang gagal itu tidak ada hubungannya dengan tabel yang rusak, sehingga
penyebabnya sulit dilihat.

DASAR PEMILIHAN — dan ini bukan tebakan, keduanya sudah diperiksa:

1. Odoo SELALU membuat primary key, termasuk pada tabel relasi many-to-many yang
   memakai primary key gabungan. Database sehat: 0 tabel tanpa primary key.
2. Saat sebuah modul di-uninstall, Odoo menghapus catatan modelnya dari
   `ir_model`. Jadi model yang masih terdaftar berarti milik modul yang masih
   terpasang.

Karena itu: **tabel tanpa primary key DAN tanpa model terdaftar berarti tabel
sisa**, dan tidak dipakai modul terpasang mana pun.

Yang TIDAK pernah dibuang skrip ini:
- tabel yang modelnya masih terdaftar (milik modul terpasang)
- tabel yang berisi data, kecuali diminta lewat --drop-with-data
- apa pun di luar skema `public`

Pemakaian:

    # 1. Lihat daftarnya
    ./odoo-venv/bin/python3 tools/cleanup_orphan_tables.py --db odoo --list

    # 2. Lihat rencananya (tidak mengubah apa pun)
    ./odoo-venv/bin/python3 tools/cleanup_orphan_tables.py --db odoo --dry-run

    # 3. Jalankan, setelah punya cadangan
    pg_dump -h 127.0.0.1 -U root -d odoo -Fc -f /tmp/odoo-sebelum-cleanup.dump
    ./odoo-venv/bin/python3 tools/cleanup_orphan_tables.py --db odoo \\
        --apply --backup-file /tmp/odoo-sebelum-cleanup.dump
"""

import argparse
import os
import sys

try:
    import psycopg2
except ImportError:  # pragma: no cover
    sys.exit(
        "psycopg2 tidak ditemukan. Jalankan dengan Python milik Odoo:\n"
        "  ./odoo-venv/bin/python3 tools/cleanup_orphan_tables.py ..."
    )


DAFTAR_KANDIDAT = """
SELECT c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname = 'public'
  AND NOT EXISTS (
      SELECT 1 FROM pg_constraint con
      WHERE con.conrelid = c.oid AND con.contype = 'p'
  )
  -- Milik modul terpasang: jangan disentuh.
  AND NOT EXISTS (
      SELECT 1 FROM ir_model m WHERE m.model = replace(c.relname, '_', '.')
  )
ORDER BY c.relname;
"""

# View yang bergantung pada tabel kandidat. View sisa juga menghalangi
# penghapusan tabel, jadi keduanya harus dibuang bersama.
#
# Sengaja memakai information_schema, bukan pg_depend: view bergantung pada
# tabel lewat *rewrite rule*, sehingga pg_depend tidak mencatatnya sebagai
# ketergantungan pg_class ke pg_class. Dengan pg_depend, daftarnya kosong dan
# penghapusan tabel akan gagal.
#
# `ir_model.table` diperiksa supaya view milik modul TERPASANG tidak ikut
# dibuang: model dengan `_auto = False` memakai SQL view sebagai tabelnya dan
# tetap terdaftar di `ir_model`.
DAFTAR_VIEW = """
SELECT DISTINCT v.view_name
FROM information_schema.view_table_usage v
WHERE v.table_schema = 'public'
  AND v.view_schema = 'public'
  AND v.table_name = ANY(%s)
  -- Nama tabel sama dengan nama model dengan titik menjadi garis bawah,
  -- termasuk untuk model ber-`_auto = False` yang memakai SQL view.
  AND NOT EXISTS (
      SELECT 1 FROM ir_model m
      WHERE replace(m.model, '.', '_') = v.view_name
  )
ORDER BY v.view_name;
"""

# Tabel terpasang yang masih menunjuk ke kandidat. Kalau ada, penghapusan akan
# gagal — dan memang seharusnya gagal, karena itu berarti tabelnya masih dipakai.
PEMAKAI = """
SELECT c.relname AS pemakai, t.relname AS target
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_class t ON t.oid = con.confrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE con.contype = 'f'
  AND n.nspname = 'public'
  AND t.relname = ANY(%s);
"""


DAFTAR_KOLOM = """
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = ANY(%s);
"""


def jumlah_baris(cr, tabel):
    cr.execute('SELECT count(*) FROM "%s"' % tabel)
    return cr.fetchone()[0]


def id_ganda(cr, tabel, punya_id):
    """Jumlah nilai `id` yang berulang. Tanda tabelnya memang sudah rusak.

    Sebagian tabel relasi tidak punya kolom `id` sama sekali — primary key-nya
    gabungan dua kolom lain — sehingga pemeriksaan ini hanya berlaku bila
    kolomnya ada.
    """
    if not punya_id:
        return 0
    cr.execute(
        """
        SELECT coalesce(sum(n - 1), 0) FROM (
            SELECT count(*) AS n FROM "%s" GROUP BY id HAVING count(*) > 1
        ) AS ganda
        """
        % tabel
    )
    return cr.fetchone()[0]


def kumpulkan(cr, verbose=False):
    cr.execute(DAFTAR_KANDIDAT)
    tabel = [r[0] for r in cr.fetchall()]
    cr.execute(DAFTAR_VIEW, (tabel,))
    view = [r[0] for r in cr.fetchall()]
    cr.execute(PEMAKAI, (tabel,))
    pemakai = cr.fetchall()

    cr.execute(DAFTAR_KOLOM, (tabel,))
    kolom = {}
    for nama_tabel, nama_kolom in cr.fetchall():
        kolom.setdefault(nama_tabel, set()).add(nama_kolom)

    rincian = []
    for nama in tabel:
        baris = jumlah_baris(cr, nama)
        punya_id = 'id' in kolom.get(nama, ())
        rincian.append({
            'nama': nama,
            'baris': baris,
            'punya_id': punya_id,
            'ganda': id_ganda(cr, nama, punya_id) if baris else 0,
        })
    return rincian, view, pemakai


def cetak(rincian, view, pemakai, judul):
    kosong = [r for r in rincian if r['baris'] == 0]
    berisi = [r for r in rincian if r['baris'] > 0]

    print("=" * 78)
    print(judul)
    print("=" * 78)
    print("  tabel sisa            : %d" % len(rincian))
    print("    kosong              : %d  (aman dibuang)" % len(kosong))
    print("    berisi data         : %d  (dilewati kecuali diminta)" % len(berisi))
    print("  view sisa             : %d" % len(view))
    print()

    if berisi:
        print("-- Tabel sisa yang BERISI DATA (tidak dibuang secara default) --")
        for r in sorted(berisi, key=lambda x: -x['baris']):
            tanda = ''
            if r['ganda']:
                tanda = '  [%d id ganda]' % r['ganda']
            elif not r['punya_id']:
                tanda = '  [tanpa kolom id]'
            print("   %-46s %6d baris%s" % (r['nama'], r['baris'], tanda))
        print()

    if view:
        print("-- View sisa yang akan dibuang --")
        for nama in view:
            print("   %s" % nama)
        print()

    if pemakai:
        print("-- PERHATIAN: tabel terpasang yang masih menunjuk ke kandidat --")
        for pemakai_nama, target in pemakai:
            print("   %s -> %s" % (pemakai_nama, target))
        print("   Baris di atas membuat penghapusan gagal. Itu memang pengaman,")
        print("   bukan kesalahan. Periksa dulu kenapa tabel itu masih dipakai.")
        print()

    return kosong, berisi


def periksa_bisa_diperbaiki(cr, nama, punya_id):
    """Apakah tabel ini bisa diberi primary key tanpa kehilangan data?

    Hanya bila kolom `id` ada, tidak ada yang kosong, dan tidak ada yang
    berulang. Id berulang berarti tabelnya memang sudah rusak — memberi primary
    key akan ditolak database, dan membersihkan duplikatnya adalah keputusan
    pemilik data, bukan keputusan skrip.
    """
    if not punya_id:
        return False, 'tanpa kolom id'
    cr.execute(
        'SELECT count(*), count(DISTINCT id), count(*) FILTER (WHERE id IS NULL) FROM "%s"'
        % nama
    )
    total, unik, kosong = cr.fetchone()
    if kosong:
        return False, '%d id kosong' % kosong
    if unik != total:
        return False, '%d id ganda' % (total - unik)
    return True, ''


def perbaiki(cr, rincian):
    """Beri primary key pada tabel sisa yang masih sehat. Data tidak dibuang."""
    berhasil, gagal = [], []
    for r in rincian:
        bisa, alasan = periksa_bisa_diperbaiki(cr, r['nama'], r['punya_id'])
        if not bisa:
            gagal.append((r['nama'], alasan))
            continue
        cr.execute('ALTER TABLE "%s" ADD PRIMARY KEY (id)' % r['nama'])
        berhasil.append(r['nama'])
    return berhasil, gagal


def jalankan(cr, kosong, view, dengan_data, daftar_data):
    dibuang = []
    for nama in view:
        cr.execute('DROP VIEW IF EXISTS "%s"' % nama)
        dibuang.append(('view', nama))
    for r in kosong:
        cr.execute('DROP TABLE "%s"' % r['nama'])
        dibuang.append(('tabel', r['nama']))
    for nama in daftar_data:
        cr.execute('DROP TABLE "%s"' % nama)
        dibuang.append(('tabel', nama))
    return dibuang


def main():
    p = argparse.ArgumentParser(
        description='Buang tabel dan view sisa milik modul yang tidak terpasang.',
    )
    p.add_argument('--db', required=True)
    p.add_argument('--host', default=os.environ.get('PGHOST', '127.0.0.1'))
    p.add_argument('--port', default=os.environ.get('PGPORT', '5432'))
    p.add_argument('--user', default=os.environ.get('PGUSER', 'root'))
    p.add_argument('--password', default=os.environ.get('PGPASSWORD', 'root'))
    p.add_argument('--list', action='store_true', help='hanya menampilkan daftar')
    p.add_argument('--dry-run', action='store_true', help='tampilkan rencana (default)')
    p.add_argument('--apply', action='store_true', help='jalankan penghapusan')
    p.add_argument(
        '--repair', action='store_true',
        help='tambahkan primary key pada tabel sisa yang masih bisa diperbaiki, '
             'supaya datanya selamat dan Odoo bisa memakainya lagi',
    )
    p.add_argument('--backup-file', help='cadangan yang sudah ada; WAJIB untuk --apply')
    p.add_argument(
        '--drop-with-data', action='store_true',
        help='ikut membuang tabel sisa yang berisi data',
    )
    args = p.parse_args()

    if args.apply and not args.backup_file:
        sys.exit(
            "Tolak jalan: --apply membutuhkan --backup-file.\n"
            "Buat dulu: pg_dump -h %s -U %s -d %s -Fc -f /tmp/%s.dump"
            % (args.host, args.user, args.db, args.db)
        )
    if args.apply and not (os.path.exists(args.backup_file) and os.path.getsize(args.backup_file) > 0):
        sys.exit("Tolak jalan: berkas cadangan %r tidak ada atau kosong." % args.backup_file)

    conn = psycopg2.connect(
        dbname=args.db, host=args.host, port=args.port,
        user=args.user, password=args.password,
    )
    conn.autocommit = False
    cr = conn.cursor()

    try:
        rincian, view, pemakai = kumpulkan(cr)
        kosong, berisi = cetak(
            rincian, view, pemakai,
            'Daftar objek sisa di database %r' % args.db,
        )

        if args.list:
            conn.rollback()
            return

        if not args.apply:
            print("Mode uji-coba. Tidak ada yang diubah.")
            print("Untuk menjalankan:")
            print("  1. pg_dump -h %s -U %s -d %s -Fc -f /tmp/%s.dump"
                  % (args.host, args.user, args.db, args.db))
            print("  2. ulangi perintah ini dengan --apply --backup-file /tmp/%s.dump"
                  % args.db)
            if berisi:
                print("     tambahkan --drop-with-data bila %d tabel berisi itu"
                      " memang tidak dibutuhkan." % len(berisi))
            conn.rollback()
            return

        # --- perbaikan dulu, bila diminta ---
        if args.repair:
            berhasil, gagal = perbaiki(cr, berisi)
            print("-- Perbaikan: primary key ditambahkan, data tetap utuh --")
            print("   berhasil : %d tabel" % len(berhasil))
            print("   gagal    : %d tabel" % len(gagal))
            for nama, alasan in gagal[:12]:
                print("      %-42s %s" % (nama, alasan))
            if len(gagal) > 12:
                print("      ... dan %d lainnya" % (len(gagal) - 12))
            print()
            # Sudah diperbaiki berarti sudah punya primary key, jadi tidak
            # dihitung sebagai kandidat lagi.
            berisi = [r for r in berisi if r['nama'] in [n for n, _ in gagal]]

        # --- jalankan ---
        daftar_data = [r['nama'] for r in berisi] if args.drop_with_data else []
        if berisi and not args.drop_with_data:
            print("%d tabel berisi data DILEWATI. Tambahkan --drop-with-data bila"
                  " memang tidak dibutuhkan." % len(berisi))
            print()

        dibuang = jalankan(cr, kosong, view, args.drop_with_data, daftar_data)
        conn.commit()
        print("=" * 78)
        print("SELESAI: %d objek dibuang (%d tabel, %d view)."
              % (len(dibuang), sum(1 for j, _ in dibuang if j == 'tabel'),
                 sum(1 for j, _ in dibuang if j == 'view')))
        print("Cadangan: %s" % args.backup_file)
        print("=" * 78)
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print()
        print("GAGAL, dan seluruh perubahan DIBATALKAN. Tidak ada yang terhapus.")
        print("  %s: %s" % (type(exc).__name__, exc))
        raise SystemExit(1)
    finally:
        cr.close()
        conn.close()


if __name__ == '__main__':
    main()
