import pathlib
import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# Ini pernah terjadi dan akibatnya berat: widget peta mendaftarkan
# `extractProps: ({ options }) => ({ options })`, sedangkan `static props`-nya
# memakai `{...standardFieldProps}` — dan `standardFieldProps` TIDAK memuat
# `options`. OWL menolak props yang tidak ada di skema:
#
#   Invalid object: unknown key 'options'
#
# Komponennya gagal dipasang, dan karena dipasang di dalam form, kegagalannya
# menjatuhkan seluruh halaman dengan galat yang tidak menyebut penyebabnya:
#
#   TypeError: this.child.mount is not a function
#
# Tes ini memeriksa berkas widgetnya langsung, karena kesalahan seperti ini tidak
# bisa ditangkap tes Odoo biasa: sisi Python-nya benar semua.
BERKAS = pathlib.Path(__file__).resolve().parent.parent / 'static' / 'src' / 'map' / 'presenly_map_field.js'
BERKAS_TEMPLAT = BERKAS.with_suffix('.xml')


@tagged('post_install', '-at_install')
class TestPresenlyMapWidgetRegistration(TransactionCase):

    def _sumber(self):
        self.assertTrue(BERKAS.exists(), 'berkas widget peta tidak ditemukan')
        return BERKAS.read_text()

    def test_setiap_prop_yang_dikirim_dideklarasikan(self):
        sumber = self._sumber()
        # Apa yang dikembalikan extractProps.
        dikirim = set(re.findall(r'extractProps:\s*\(\{([^}]*)\}\)', sumber))
        nama = {n.strip() for blok in dikirim for n in blok.split(',') if n.strip()}
        self.assertTrue(nama, 'extractProps tidak ditemukan di widget peta')

        # Apa yang dideklarasikan di skema props.
        blok = re.search(r'static props = \{(.*?)\n    \};', sumber, re.S)
        self.assertTrue(blok, 'static props tidak ditemukan')
        skema = blok.group(1)

        hilang = [n for n in sorted(nama) if not re.search(r'\b%s\s*:' % re.escape(n), skema)]
        self.assertEqual(
            hilang, [],
            'prop %s dikirim extractProps tapi tidak ada di static props; '
            'OWL akan menolak komponennya dan seluruh form ikut gagal' % hilang,
        )

    def test_widget_menangani_galatnya_sendiri(self):
        # Widget ini memuat pustaka dari jaringan dan menggambar DOM. Tanpa
        # penanganan sendiri, satu kegagalan membuang seluruh pohon komponen.
        self.assertIn('onError(', self._sumber())

    def _templat(self):
        """Isi templat tanpa komentar; komentar boleh menyebut bentuk yang dilarang."""
        self.assertTrue(BERKAS_TEMPLAT.exists(), 'berkas templat widget peta tidak ditemukan')
        return re.sub(r'<!--.*?-->', '', BERKAS_TEMPLAT.read_text(), flags=re.S)

    def test_templat_tidak_memakai_interpolasi_owl_1(self):
        # OWL 2 memakai `{{ }}`; bentuk `#{ }` dari OWL 1 tidak dilaporkan
        # sebagai galat, hanya menghasilkan teks yang salah diam-diam.
        self.assertNotIn('#{', self._templat(), 'interpolasi `#{ }` bukan sintaks OWL 2')

    def test_ekspresi_templat_memakai_sintaks_javascript(self):
        # Ekspresi di templat OWL diperiksa dengan **JavaScript**; penanda view
        # (`invisible`, `readonly`) justru diperiksa dengan **Python** di server.
        # Keduanya berbeda, dan menyamakannya tidak memunculkan galat yang
        # menyebut barisnya:
        #
        #   Failed to compile template "presenly_saas.MapField":
        #   Unexpected identifier 'ctx'
        #
        # Halaman form-nya lalu mati dengan dialog "Oops!", dan penyebabnya hanya
        # terlihat setelah detail teknisnya dibuka.
        templat = self._templat()
        ekspresi = re.findall(r'\bt-(?:if|elif|esc|out|att-[\w-]+)="([^"]*)"', templat)
        bersalah = [
            teks for teks in ekspresi
            if re.search(r'(?<![\w.])(and|or|not)(?![\w])', teks)
        ]
        self.assertEqual(
            bersalah, [],
            'ekspresi templat OWL memakai operator Python: %s. Pakai &&, ||, ! '
            'atau pindahkan syaratnya ke getter.' % bersalah,
        )

    def test_teks_tidak_dirakit_di_dalam_templat(self):
        # Bentuk `<t t-out>` yang bercampur teks di dalam elemen bersyarat pernah
        # menjatuhkan widget ini di bundel produksi (bukan di mode `--dev`,
        # karena aset produksi di-minify):
        #
        #   TypeError: this.child.mount is not a function
        #
        # Teksnya karena itu dirakit di JavaScript, dan templat hanya memasang
        # satu `t-out` per elemen bersyarat.
        templat = self._templat()
        self.assertNotIn('<t t-out', templat, 'rakit teks di JavaScript, bukan di templat')
        for nama in ('legendOffice', 'legendPoint', 'missingFieldsText'):
            self.assertIn(nama, self._sumber(), '%s harus ada di komponen' % nama)
