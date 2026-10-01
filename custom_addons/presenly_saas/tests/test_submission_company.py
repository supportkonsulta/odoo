"""Pemisahan data pengajuan: per perusahaan, dan per cabang dari lokasinya.

Fokus lembur lebih dulu, karena ialah yang dipakai payroll. Cabang pada baris
pengajuan **diturunkan** dari lokasi kerjanya: payload pengajuan tidak membawa
klien, hanya lokasi. Isi berkas ini menjaga empat hal yang mudah rusak tanpa
terlihat:

1. penurunannya lewat id lokasi, bukan lewat namanya;
2. baris yang lokasinya belum tercermin dibiarkan kosong, bukan ditebak;
3. cabang yang sudah terisi tidak ditulis ulang, karena pengajuan adalah catatan
   masa lalu;
4. aturan perusahaan benar-benar menyaring, bukan sekadar ada.
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


def overtime_row(**overrides):
    row = {
        'id': 9001,
        'overtime_date': '2026-09-21',
        'purpose': 'Penutupan bulan',
        'start_time': '17:00:00',
        'end_time': '19:00:00',
        'total_hours': 2.0,
        'day_type': 'workday',
        'within_radius': True,
        'overtime_pay': 150000.0,
        'approval_status': 'approved',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'location': {'id': 501, 'name': 'Lokasi Uji'},
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlySubmissionBranch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)
        cls.Overtime = cls.env['presenly.saas.overtime']
        cls.Location = cls.env['presenly.saas.work.location']

    def setUp(self):
        super().setUp()
        self.Overtime.search([]).unlink()
        self.Location.search([]).unlink()

    def _lokasi(self, external_id, klien_id, nama='Lokasi Uji'):
        return self.Location.create({
            'external_id': external_id,
            'name': nama,
            'company_id': self.company.id,
            'internal_company_id': klien_id,
            'internal_company_name': 'CLIENT %s' % klien_id,
        })

    # ------------------------------------------------------------------
    # Cabang diturunkan dari lokasi
    # ------------------------------------------------------------------
    def test_cabang_diturunkan_dari_lokasi(self):
        cabang = self._perusahaan(1)
        self._lokasi(501, 1)

        self.Overtime._mirror_replace(self.company, [overtime_row()])

        baris = self.Overtime.search([('external_id', '=', 9001)])
        self.assertEqual(baris.location_id, 501, 'id lokasinya disimpan')
        self.assertEqual(baris.tenant_client_id, 1)
        self.assertEqual(baris.tenant_client_name, 'CLIENT 1')
        self.assertEqual(
            baris.tenant_client_company_id, cabang,
            'perusahaan cabangnya ikut dicatat: itu yang dipakai aturan dan payroll',
        )

    def test_penurunan_lewat_id_bukan_nama(self):
        """Nama lokasi boleh berbeda dari yang dikirim payload."""
        self._lokasi(501, 2, nama='Nama Sudah Diubah di Presenly')

        self.Overtime._mirror_replace(self.company, [overtime_row()])

        baris = self.Overtime.search([('external_id', '=', 9001)])
        self.assertEqual(baris.location_name, 'Lokasi Uji', 'nama dari payload')
        self.assertEqual(
            baris.tenant_client_name, 'CLIENT 2',
            'cabangnya dari lokasi yang dicocokkan lewat id',
        )

    def test_lokasi_yang_belum_tercermin_dibiarkan_kosong(self):
        """Dibiarkan kosong, bukan ditebak.

        Cabang yang salah lebih berbahaya daripada cabang yang kosong: yang salah
        tidak terlihat, sedangkan yang kosong bisa ditanyakan.
        """
        self.Overtime._mirror_replace(self.company, [overtime_row()])

        baris = self.Overtime.search([('external_id', '=', 9001)])
        self.assertEqual(baris.location_id, 501, 'id lokasinya tetap disimpan')
        self.assertFalse(baris.tenant_client_name)
        self.assertFalse(baris.tenant_client_id)

    def test_cabang_yang_sudah_terisi_tidak_ditimpa(self):
        """Pengajuan adalah catatan masa lalu.

        Kalau lokasinya suatu saat berpindah klien, baris yang sudah tercatat
        tetap memakai klien saat pengajuannya terjadi.

        Yang diuji adalah jalur **penarikan** (`_mirror_upsert`), karena itulah
        yang dipakai pengajuan: ia memperbarui barisnya. Penggantian menyeluruh
        memang membuat ulang barisnya, jadi di sana cabangnya wajar diturunkan
        lagi; membedakan keduanya di sini supaya perbedaannya tidak hilang.
        """
        lokasi = self._lokasi(501, 1)
        self.Overtime._mirror_replace(self.company, [overtime_row()])
        lokasi.write({'internal_company_id': 9, 'internal_company_name': 'CLIENT 9'})

        self.Overtime._mirror_upsert(self.company, [overtime_row()])

        baris = self.Overtime.search([('external_id', '=', 9001)])
        self.assertEqual(baris.tenant_client_name, 'CLIENT 1', 'yang lama dipertahankan')

    def test_tarikan_ulang_tidak_menghapus_cabang(self):
        """Penarikan berikutnya menulis ulang barisnya, bukan cabangnya."""
        self._lokasi(501, 1)
        self.Overtime._mirror_replace(self.company, [overtime_row()])

        self.Overtime._mirror_upsert(self.company, [overtime_row(purpose='Diubah')])

        baris = self.Overtime.search([('external_id', '=', 9001)])
        self.assertEqual(baris.purpose, 'Diubah')
        self.assertEqual(baris.tenant_client_name, 'CLIENT 1')

    # ------------------------------------------------------------------
    # Isi lama, dari payload yang tersimpan
    # ------------------------------------------------------------------
    def test_isi_lama_dapat_id_lokasi_dari_payload(self):
        """Migrasi tidak perlu memanggil API sama sekali."""
        baris = self.Overtime.sudo().create({
            'external_id': 9002,
            'company_id': self.company.id,
            'overtime_date': '2026-09-21',
            'raw_payload': {'location': {'id': 777, 'name': 'Lokasi Lama'}},
        })
        self.assertEqual(baris.location_id, 0, 'prasyarat: baris lama')

        diisi = self.Overtime._mirror_fill_location_ids_from_payload(self.company)

        self.assertEqual(diisi, 1)
        self.assertEqual(baris.location_id, 777)

    def test_isi_lama_tanpa_lokasi_tidak_dianggap_gagal(self):
        self.Overtime.sudo().create({
            'external_id': 9003,
            'company_id': self.company.id,
            'overtime_date': '2026-09-21',
            'raw_payload': {'purpose': 'tanpa lokasi'},
        })

        self.assertEqual(
            self.Overtime._mirror_fill_location_ids_from_payload(self.company), 0,
        )

    # ------------------------------------------------------------------
    # Pemisahan per perusahaan
    # ------------------------------------------------------------------
    def test_tenant_lain_tidak_terlihat(self):
        """Pagar tenant: perusahaan pusat yang tidak diizinkan tidak terlihat.

        Diuji lewat pengelola, karena dialah yang aturannya melihat seluruh
        cabang di perusahaan yang ia diizinkan. Kalau pagarnya hilang, pengelola
        satu tenant bisa melihat pengajuan tenant lain.
        """
        perusahaan_lain = self.env['res.company'].create({'name': 'Tenant Lain'})
        other = self.Overtime.sudo().create({
            'external_id': 9004,
            'company_id': perusahaan_lain.id,
            'overtime_date': '2026-09-21',
        })
        pengelola = self._pengguna(
            'uji.pengelola.tenant',
            [self.env.ref('presenly_saas.group_presenly_saas_manager')],
            [self.company],
        )

        self.assertNotIn(other, self.Overtime.with_user(pengelola).search([]))

    # ------------------------------------------------------------------
    # Siapa yang melihat cabang mana
    # ------------------------------------------------------------------
    def _perusahaan(self, klien_id):
        return self.env['res.company'].create({
            'name': 'CLIENT %s' % klien_id,
            'presenly_client_id': klien_id,
        })

    def _pengguna(self, login, groups, companies):
        return self.env['res.users'].create({
            'name': login,
            'login': login,
            'company_id': self.company.id,
            'company_ids': [(6, 0, [c.id for c in companies])],
            'group_ids': [(6, 0, [g.id for g in groups])],
        })

    def _tiga_baris(self):
        """Dua baris bercabang, satu tanpa cabang (lokasinya belum tercermin).

        Perusahaan cabangnya dibuat lebih dulu: tanpa itu, cabangnya tidak bisa
        diturunkan menjadi perusahaan, dan aturan cabang akan menyaring semuanya.
        Mengembalikan kedua perusahaan cabang itu untuk dipakai tesnya.
        """
        cabang_1 = self._perusahaan(1)
        cabang_2 = self._perusahaan(2)
        self._lokasi(501, 1)
        self._lokasi(502, 2, nama='Lokasi Dua')
        self.Overtime._mirror_replace(self.company, [
            overtime_row(id=9001, location={'id': 501, 'name': 'Lokasi Uji'}),
            overtime_row(id=9002, location={'id': 502, 'name': 'Lokasi Dua'}),
            overtime_row(id=9003, location={'id': 999, 'name': 'Belum Tercermin'}),
        ])
        return cabang_1, cabang_2

    def test_pengelola_melihat_semua_cabang(self):
        """Pengelola integrasi ada di perusahaan pusat, jadi melihat semuanya."""
        self._tiga_baris()
        pengelola = self._pengguna(
            'uji.pengelola', [self.env.ref('presenly_saas.group_presenly_saas_manager')],
            [self.company],
        )

        self.assertEqual(self.Overtime.with_user(pengelola).search_count([]), 3)

    def test_pengguna_cabang_hanya_melihat_cabangnya(self):
        """Tanpa modul HR, aturan cabang masih berlaku untuk pengguna internal.

        Begitu `presenly_saas_hr` terpasang, grup internal dikeluarkan dari
        aturan ini dan diganti grup Approver, lalu ditambahkan aturan "milik
        sendiri": pengguna biasa hanya melihat barisnya. Perilaku itu diuji di
        `presenly_saas_hr/tests/test_own_data_rules.py`, karena aturannya memang
        tinggal di sana.
        """
        hr_terpasang = self.env['ir.module.module'].search_count([
            ('name', '=', 'presenly_saas_hr'), ('state', '=', 'installed'),
        ])
        if hr_terpasang:
            self.skipTest('presenly_saas_hr memindahkan aturan cabang ke Approver')

        cabang_1, _cabang_2 = self._tiga_baris()
        pengguna = self._pengguna(
            'uji.cabang.satu', [self.env.ref('base.group_user')],
            [self.company, cabang_1],
        )

        terlihat = self.Overtime.with_user(pengguna).search([]).mapped('external_id')

        self.assertEqual(
            terlihat, [9001],
            'hanya cabangnya sendiri; baris cabang lain dan yang belum berlabel '
            'tidak terlihat',
        )

    def test_pengguna_tanpa_cabang_tidak_melihat_apa_pun(self):
        """Bukan HR, bukan pengelola, dan tidak di cabang mana pun.

        Keputusan pemilik: lintas cabang hanya untuk HR di perusahaan pusat. Jadi
        pengguna pusat yang bukan HR tidak melihat pengajuan cabang mana pun,
        termasuk yang belum berlabel.
        """
        self._tiga_baris()
        pengguna = self._pengguna(
            'uji.tanpa.cabang', [self.env.ref('base.group_user')], [self.company],
        )

        self.assertEqual(self.Overtime.with_user(pengguna).search_count([]), 0)

    def test_hr_melihat_semua_cabang(self):
        """Keputusan pemilik: HR di perusahaan pusat melihat lintas cabang.

        Pintu untuk HR ada di `presenly_saas_hr` (grup HR hanya ada bila `hr`
        terpasang, sedangkan modul ini dipakai juga tanpanya). Tanpa modul itu
        tidak ada aturan yang membuka cabang untuk HR, jadi ujinya dilewati -
        bukan dianggap gagal.
        """
        grup_hr = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
        hr_terpasang = self.env['ir.module.module'].search_count([
            ('name', '=', 'presenly_saas_hr'), ('state', '=', 'installed'),
        ])
        if not grup_hr or not hr_terpasang:
            self.skipTest('aturan HR ada di presenly_saas_hr')
        self._tiga_baris()
        pengguna = self._pengguna('uji.hr', [grup_hr], [self.company])

        self.assertEqual(self.Overtime.with_user(pengguna).search_count([]), 3)

    # ------------------------------------------------------------------
    # Tampilan
    # ------------------------------------------------------------------
    def test_view_lembur_menampilkan_cabang_dan_perusahaan(self):
        from lxml import etree
        daftar = etree.fromstring(
            self.env.ref('presenly_saas.view_presenly_saas_overtime_list').arch
        )
        self.assertTrue(
            daftar.xpath("//field[@name='tenant_client_name']"),
            'kolom cabang harus ada di daftar lembur',
        )
        kolom_perusahaan = daftar.xpath("//field[@name='company_id']")
        self.assertTrue(kolom_perusahaan, 'kolom perusahaan harus ada')
        self.assertIn(
            'base.group_multi_company', kolom_perusahaan[0].get('groups') or '',
            'kolom perusahaan hanya untuk pengguna multi-company',
        )

        cari = etree.fromstring(
            self.env.ref('presenly_saas.view_presenly_saas_overtime_search').arch
        )
        self.assertTrue(cari.xpath("//filter[@name='group_internal_company']"))
        self.assertTrue(cari.xpath("//filter[@name='group_location']"))
        self.assertTrue(cari.xpath("//field[@name='company_id']"))
