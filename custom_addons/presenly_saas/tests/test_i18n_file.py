import pathlib

try:
    import polib
except ImportError:  # pragma: no cover
    polib = None

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# Berkas terjemahan pernah rusak tiga kali dalam pekerjaan ini, dengan dua
# akibat berbeda yang keduanya tidak terlihat dari tes biasa:
#
#   1. Entri ditambahkan tanpa komentar `#. module:` → Odoo tidak bisa menentukan
#      berkas ini milik modul mana, dan pemuatan terjemahan gagal dengan
#      "'NoneType' object has no attribute 'groups'" — yang membuat INSTALASI
#      modul gagal, bukan sekadar terjemahannya kosong.
#   2. Berkas disusun ulang dari nol → ratusan terjemahan hilang tanpa pesan
#      apa pun, dan yang terlihat hanya beberapa label kembali berbahasa Inggris.
#
# Keduanya hanya ketahuan kalau ada yang memeriksa berkasnya. Itu yang dilakukan
# tes ini.
MINIMAL_ENTRI = 100


@tagged('post_install', '-at_install')
class TestPresenlyTranslationFile(TransactionCase):

    def _berkas(self):
        return pathlib.Path(__file__).resolve().parent.parent / 'i18n' / 'id.po'

    def test_berkas_terjemahan_ada(self):
        self.assertTrue(self._berkas().exists(), 'i18n/id.po tidak ditemukan')

    def test_setiap_entri_punya_komentar_module(self):
        if polib is None:
            self.skipTest('polib tidak tersedia')
        tanpa = [
            entry.msgid for entry in polib.pofile(str(self._berkas()))
            if entry.msgid and not (entry.comment or '').startswith(('module:', 'modules:'))
        ]
        # Inilah yang membuat Odoo gagal memuat berkasnya.
        self.assertEqual(tanpa, [], 'entri tanpa komentar module: %s' % tanpa[:3])

    def test_tidak_ada_terjemahan_kosong(self):
        if polib is None:
            self.skipTest('polib tidak tersedia')
        kosong = [
            entry.msgid for entry in polib.pofile(str(self._berkas()))
            if entry.msgid and not entry.msgstr.strip()
        ]
        self.assertEqual(kosong, [], 'entri tanpa terjemahan: %s' % kosong[:3])

    def test_jumlah_entri_tidak_menyusut(self):
        # Penjaga terhadap penyusunan ulang yang menghapus terjemahan: jumlahnya
        # hanya boleh bertambah, dan tidak pernah turun di bawah batas ini.
        if polib is None:
            self.skipTest('polib tidak tersedia')
        jumlah = len([e for e in polib.pofile(str(self._berkas())) if e.msgid])
        self.assertGreaterEqual(
            jumlah, MINIMAL_ENTRI,
            'berkas terjemahan hanya berisi %d entri; penyusunan ulang mungkin '
            'menghapus terjemahan yang sudah ada' % jumlah,
        )

    def test_placeholder_tidak_hilang(self):
        # Terjemahan yang kehilangan `%(nama)s` akan membuat pesan rusak saat
        # dijalankan, dan itu tidak terlihat sampai ada yang membacanya.
        if polib is None:
            self.skipTest('polib tidak tersedia')
        import re
        pola = re.compile(r'%\([a-z_]+\)s|%s|%d')
        rusak = []
        for entry in polib.pofile(str(self._berkas())):
            if not entry.msgid:
                continue
            if sorted(pola.findall(entry.msgid)) != sorted(pola.findall(entry.msgstr)):
                rusak.append(entry.msgid[:50])
        self.assertEqual(rusak, [], 'placeholder tidak sama: %s' % rusak[:3])
