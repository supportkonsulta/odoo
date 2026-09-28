from datetime import timedelta
from unittest import mock

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPresenlyPlacementBranches(TransactionCase):
    """Cabang per pegawai, dan akses perusahaan yang mengikutinya.

    Satu pegawai bisa ditempatkan di beberapa klien sekaligus: satu baris
    `placements` per pegawai dan klien. Daftar cabangnya adalah keadaan
    **sekarang**, sedangkan akses perusahaannya hanya bertambah — keputusan
    pemilik, supaya tidak ada yang kehilangan perusahaan di tengah pekerjaan
    tanpa diminta.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['presenly.saas.config'].search([], limit=1)
        cls.Mirror = cls.env['presenly.saas.employee']
        cls.Hr = cls.env['hr.employee'].with_context(active_test=False)

    def setUp(self):
        super().setUp()
        self.cabang_a = self.env['res.company'].create({
            'name': 'Cabang A', 'presenly_client_id': 9001,
        })
        self.cabang_b = self.env['res.company'].create({
            'name': 'Cabang B', 'presenly_client_id': 9002,
        })
        self.pengguna = self.env['res.users'].create({
            'name': 'Pegawai Uji',
            'login': 'uji.cabang.presenly',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })

    # ------------------------------------------------------------------
    # Bantu
    # ------------------------------------------------------------------
    def _pegawai(self, nopeg, dengan_akun=True):
        """Cermin dan `hr.employee`, sudah tertaut.

        Penautannya dilakukan di sini karena penempatan bekerja dari cermin ke
        pegawai lewat `hr_employee_id`; tanpa tautan itu, penempatan dilewati dan
        tesnya gagal karena sebab yang tidak ada hubungannya dengan cabang.
        """
        cermin = self.Mirror.create({
            'external_id': 8000 + len(nopeg),
            'nopeg': nopeg,
            'name': 'Pegawai %s' % nopeg,
            'company_id': self.config.company_id.id,
        })
        hr = self.Hr.create({
            'name': 'Pegawai %s' % nopeg,
            'presenly_nopeg': nopeg,
            'user_id': self.pengguna.id if dengan_akun else False,
        })
        cermin.hr_employee_id = hr.id
        return hr

    def _penempatan(self, nopeg, cabang, utama=False, mulai='2026-01-01',
                    sampai=False, status='active', external_id=1):
        return {
            'id': external_id,
            'employee': {'id': external_id, 'nopeg': nopeg, 'name': 'Pegawai %s' % nopeg},
            'internal_company': {'id': cabang.presenly_client_id, 'name': cabang.name},
            'status': status,
            'is_primary': utama,
            'valid_from': mulai,
            'valid_until': sampai,
        }

    def _tarik(self, baris, total=None):
        """Tarik penempatan dengan jaringan dipalsukan.

        ``total`` dipakai untuk memalsukan respons yang terpotong: jumlah baris
        yang diterima lebih sedikit daripada yang diakui server.
        """
        meta = {'total': total if total is not None else len(baris)}
        with mock.patch.object(type(self.config), '_client', lambda self: mock.Mock()), \
             mock.patch.object(type(self.config), '_fetch_pages',
                               lambda *a, **k: (baris, meta, 1)):
            return self.config._pull_placements()

    # ------------------------------------------------------------------
    # Daftar cabang
    # ------------------------------------------------------------------
    def test_daftar_cabang_dari_seluruh_penempatan(self):
        """Penempatan utama hanya satu, tetapi cabangnya bisa beberapa."""
        hr = self._pegawai('uji-dua-cabang')

        ringkas, error = self._tarik([
            self._penempatan('uji-dua-cabang', self.cabang_a, utama=True, external_id=1),
            self._penempatan('uji-dua-cabang', self.cabang_b, external_id=2),
        ])

        self.assertFalse(error)
        self.assertEqual(
            hr.presenly_client_ids, self.cabang_a | self.cabang_b,
            'kedua cabangnya tercatat, bukan hanya yang utama',
        )
        self.assertEqual(ringkas['branches'], 1)

    def test_penempatan_yang_sudah_berakhir_tidak_ikut(self):
        hr = self._pegawai('uji-berakhir')

        self._tarik([
            self._penempatan('uji-berakhir', self.cabang_a, utama=True, external_id=3),
            self._penempatan('uji-berakhir', self.cabang_b, external_id=4,
                             mulai='2025-01-01', sampai='2025-06-30'),
        ])

        self.assertEqual(hr.presenly_client_ids, self.cabang_a)

    def test_penempatan_yang_belum_mulai_tidak_memberi_akses_lebih_awal(self):
        hr = self._pegawai('uji-belum-mulai')

        self._tarik([
            self._penempatan('uji-belum-mulai', self.cabang_a, utama=True, external_id=5),
            self._penempatan('uji-belum-mulai', self.cabang_b, external_id=6,
                             mulai=fields.Date.to_string(
                                 fields.Date.context_today(self) + timedelta(days=30)
                             )),
        ])

        self.assertEqual(hr.presenly_client_ids, self.cabang_a)

    def test_penempatan_yang_dibatalkan_tidak_ikut(self):
        hr = self._pegawai('uji-dibatalkan')

        self._tarik([
            self._penempatan('uji-dibatalkan', self.cabang_a, utama=True, external_id=7),
            self._penempatan('uji-dibatalkan', self.cabang_b, external_id=8,
                             status='inactive'),
        ])

        self.assertEqual(hr.presenly_client_ids, self.cabang_a)

    def test_daftar_cabang_dikosongkan_saat_penempatannya_hilang(self):
        hr = self._pegawai('uji-hilang-cabang')
        self._tarik([self._penempatan('uji-hilang-cabang', self.cabang_a, utama=True)])

        self._tarik([])

        self.assertFalse(hr.presenly_client_ids, 'daftarnya keadaan sekarang')
        self.assertIn(
            self.cabang_a, self.pengguna.company_ids,
            'tetapi akses perusahaannya tidak dicabut',
        )

    def test_tarikan_terpotong_tidak_menghapus_cabang(self):
        """Daftar yang belum lengkap bukan bukti penempatannya hilang."""
        hr = self._pegawai('uji-terpotong')
        self._tarik([self._penempatan('uji-terpotong', self.cabang_a, utama=True)])

        _ringkas, _error = self._tarik([], total=5)

        self.assertEqual(
            hr.presenly_client_ids, self.cabang_a,
            'cabangnya tetap; yang diterima baru sebagian',
        )

    # ------------------------------------------------------------------
    # Akses perusahaan
    # ------------------------------------------------------------------
    def test_akses_perusahaan_diberikan_ke_pengguna(self):
        self._pegawai('uji-akses')

        ringkas, error = self._tarik([
            self._penempatan('uji-akses', self.cabang_a, utama=True, external_id=9),
            self._penempatan('uji-akses', self.cabang_b, external_id=10),
        ])

        self.assertFalse(error)
        self.assertEqual(ringkas['access_granted'], 2)
        self.assertIn(self.cabang_a, self.pengguna.company_ids)
        self.assertIn(self.cabang_b, self.pengguna.company_ids)

    def test_pemberian_akses_tercatat_di_log(self):
        """Pertanyaan \"kenapa orang ini punya perusahaan itu\" harus terjawab."""
        self._pegawai('uji-log')
        self._tarik([self._penempatan('uji-log', self.cabang_a, utama=True)])

        catatan = self.env['presenly.saas.sync.log'].sudo().search([
            ('endpoint', '=', 'access.companies'),
        ])
        self.assertTrue(catatan, 'pemberian akses meninggalkan satu baris log')
        self.assertIn('Cabang A', catatan[0].error_message)

    def test_akses_tidak_pernah_dicabut(self):
        """Keputusan pemilik: hanya menambah, supaya tidak ada kejutan."""
        self._pegawai('uji-tidak-dicabut')
        self._tarik([self._penempatan('uji-tidak-dicabut', self.cabang_a, utama=True)])
        self.pengguna.write({'company_ids': [(3, self.cabang_a.id)]})

        self._tarik([self._penempatan('uji-tidak-dicabut', self.cabang_a, utama=True)])

        self.assertIn(
            self.cabang_a, self.pengguna.company_ids,
            'yang dihapus orang ditambahkan lagi oleh tarikan berikutnya, '
            'dan itu memang perilaku yang dipilih',
        )

    def test_akses_tidak_diberikan_untuk_perusahaan_bukan_cermin_klien(self):
        """Yang diberikan hanya perusahaan hasil cermin klien."""
        pegawai = self._pegawai('uji-bukan-cermin')

        self._tarik([{
            'id': 11,
            'employee': {'id': 11, 'nopeg': 'uji-bukan-cermin', 'name': 'Pegawai Uji'},
            'internal_company': {'id': 987654, 'name': 'Klien Belum Dibuat'},
            'status': 'active', 'is_primary': True, 'valid_from': '2026-01-01',
        }])

        self.assertFalse(pegawai.presenly_client_ids)
        self.assertEqual(
            set(self.pengguna.company_ids.ids),
            {self.config.company_id.id},
            'perusahaan yang bukan cermin klien tidak pernah ditambahkan',
        )

    def test_cermin_menampilkan_cabang_yang_berlaku(self):
        """Halaman cermin ikut menjawab "cabangnya mana".

        Payload pegawai hanya membawa satu klien, dan sering tidak membawa sama
        sekali. Daftar yang berlaku datang dari penempatan, jadi halaman cermin
        harus bisa menampilkannya juga, bukan hanya halaman pegawai.
        """
        self._pegawai('uji-cermin-cabang')
        self._tarik([
            self._penempatan('uji-cermin-cabang', self.cabang_a, utama=True, external_id=21),
            self._penempatan('uji-cermin-cabang', self.cabang_b, external_id=22),
        ])

        cermin = self.Mirror.search([('nopeg', '=', 'uji-cermin-cabang')], limit=1)
        self.assertEqual(cermin.branch_ids, self.cabang_a | self.cabang_b)

    def test_akun_yang_baru_ditautkan_langsung_mendapat_cabangnya(self):
        """Bukan menunggu tarikan berikutnya.

        Pertanyaan yang dijawab: panggi akunnya baru dibuat untuk pegawai yang
        sudah punya cabang, apakah ia harus menunggu cron besok.
        """
        hr = self._pegawai('uji-akun-baru', dengan_akun=False)
        self._tarik([self._penempatan('uji-akun-baru', self.cabang_a, utama=True)])
        self.assertFalse(
            self.pengguna.company_ids & self.cabang_a,
            'prasyarat: belum ada akun, jadi belum ada akses',
        )

        hr.with_context(presenly_skip_push=True).write({'user_id': self.pengguna.id})

        self.assertIn(self.cabang_a, self.pengguna.company_ids)
        self.assertTrue(
            self.env['presenly.saas.sync.log'].sudo().search_count([
                ('endpoint', '=', 'access.companies'),
            ]),
            'pemberiannya juga tercatat',
        )

    def test_pegawai_tanpa_akun_tidak_diganggu(self):
        pegawai = self._pegawai('uji-tanpa-akun', dengan_akun=False)

        ringkas, error = self._tarik([
            self._penempatan('uji-tanpa-akun', self.cabang_a, utama=True),
        ])

        self.assertFalse(error)
        self.assertEqual(pegawai.presenly_client_ids, self.cabang_a)
        self.assertEqual(ringkas['access_granted'], 0)

    def test_cabang_tidak_menyentuh_pegawai_konfigurasi_lain(self):
        """Nopeg yang sama di konfigurasi lain tidak boleh ikut tersentuh."""
        pegawai_lain = self.Hr.create({
            'name': 'Pegawai Konfigurasi Lain',
            'presenly_nopeg': 'uji-cabang-lain',
        })
        self._pegawai('uji-cabang-lain')

        self._tarik([self._penempatan('uji-cabang-lain', self.cabang_a, utama=True)])

        self.assertFalse(
            pegawai_lain.presenly_client_ids,
            'yang tidak tertaut ke cermin konfigurasi ini tidak disentuh',
        )
