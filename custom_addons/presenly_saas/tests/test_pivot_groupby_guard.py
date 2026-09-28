"""Pivot: kelompok yang sudah dipakai tidak ditawarkan lagi.

Pivot Odoo membiarkan kelompok yang sama ditambahkan berulang kali — menunya
berisi seluruh pilihan group-by tanpa memeriksa yang sudah dipakai. Akibatnya
satu baris bisa dibuka tanpa henti, dan tiap lapisnya hanya mengulang nilai di
atasnya dengan angka yang sama persis.

Penjaganya ada di berkas JavaScript dan templat, karena itu satu-satunya tempat
yang bisa mengubah perilaku pivot tanpa menyentuh Odoo sendiri. Tes ini
memeriksa sifat yang harus ada di berkas-berkas itu; sisi Python-nya benar
semua, jadi kesalahan di sana tidak bisa ditangkap tes Odoo biasa — sama seperti
widget peta.
"""

import pathlib
import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / 'static' / 'src' / 'pivot'
)
BERKAS = DIR / 'presenly_pivot_groupby.js'
BERKAS_TEMPLAT = DIR / 'presenly_pivot_groupby.xml'

ASET = 'presenly_saas/static/src/pivot/presenly_pivot_groupby'


@tagged('post_install', '-at_install')
class TestPresenlyPivotGroupByGuard(TransactionCase):

    def _sumber(self):
        self.assertTrue(BERKAS.exists(), 'berkas penjaga pivot tidak ditemukan')
        return BERKAS.read_text()

    def _templat(self):
        self.assertTrue(BERKAS_TEMPLAT.exists(), 'templat penjaga pivot tidak ditemukan')
        return BERKAS_TEMPLAT.read_text()

    def _aset(self):
        import odoo.modules.module as module

        return module.get_manifest('presenly_saas')['assets']['web.assets_backend']

    def test_kedua_berkas_terdaftar_sebagai_aset_backend(self):
        """Berkas yang tidak didaftarkan tidak pernah dimuat — dan itu senyap."""
        aset = self._aset()
        self.assertIn(ASET + '.js', aset, 'penjaga pivot harus terdaftar')
        self.assertIn(ASET + '.xml', aset, 'templatnya juga, kalau tidak ikonnya tidak berubah')

    def test_menutup_dua_jalur_data(self):
        """Menu biasa dan menu "Custom Group By" lewat jalur yang berbeda.

        Menyaring menunya saja tidak cukup: daftar kolom di "Custom Group By"
        tidak lewat penyaringan itu, jadi modelnya sendiri harus menolak.
        """
        sumber = self._sumber()
        self.assertIn('PivotRenderer.prototype', sumber)
        self.assertIn('PivotModel.prototype', sumber)

    def test_perilaku_asli_tetap_dijalankan(self):
        """Tanpa `super`, penjaganya menggantikan perilaku pivot, bukan menambah."""
        sumber = self._sumber()
        self.assertIn('super.groupByItems', sumber)
        self.assertIn('super.addGroupBy', sumber)
        self.assertIn('super.onHeaderClick', sumber)

    def test_gagal_dengan_aman(self):
        """Yang tidak dikenali diperlakukan seperti sebelumnya.

        Pivot yang rusak karena penjaga ini jauh lebih buruk daripada pivot yang
        masih bisa dibuka berulang kali.
        """
        sumber = self._sumber()
        self.assertIn('if (!terpakai)', sumber)
        self.assertIn('if (!info)', sumber)

    def test_membandingkan_kelompoknya_bukan_kolomnya(self):
        """`work_date:month` dan `work_date:year` menjawab pertanyaan berbeda.

        Membandingkan kolomnya saja membuat bulan dan tahun pada kolom yang sama
        saling meniadakan — padahal keduanya sah dipakai berdampingan.
        """
        sumber = self._sumber()
        self.assertIn('${params.fieldName}:${params.interval}', sumber)
        self.assertIn('${item.fieldName}:${option.id}', sumber)

    def test_ikon_hilang_saat_pilihan_habis(self):
        """Ikon buka hanya muncul kalau masih ada yang bisa dibuka."""
        templat = self._templat()
        self.assertIn('t-inherit="web.PivotHeader.title"', templat)
        self.assertIn('this.bisaDibuka(isXAxis)', templat)
        # Ikon tutup tidak boleh ikut hilang: menutup lapisan selalu punya arti.
        self.assertIn('!cell.isLeaf or', templat)
        self.assertIn('bisaDibuka(', self._sumber())

    def test_klik_tanpa_pilihan_tidak_membuka_menu(self):
        """Ikon yang disembunyikan tidak boleh digantikan menu kosong."""
        sumber = self._sumber()
        self.assertIn('onHeaderClick(ev, cell, isXAxis)', sumber)
        self.assertIn('!this.bisaDibuka(isXAxis)', sumber)

    def test_terjemahan_tidak_dirakit_di_dalam_js(self):
        """Tidak ada teks pengguna di berkas ini, jadi tidak ada yang perlu `_t`."""
        sumber = self._sumber()
        self.assertNotIn('_t(', sumber, 'berkas ini tidak menampilkan teks apa pun')
